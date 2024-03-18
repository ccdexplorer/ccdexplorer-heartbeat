# ruff: noqa: F403, F405, E402, E501, E722
import asyncio
from heartbeat import Heartbeat
from ccdefundamentals.GRPCClient import GRPCClient
from ccdefundamentals.GRPCClient.CCD_Types import *
from ccdefundamentals.tooter import Tooter
from ccdefundamentals.mongodb import (
    MongoDB,
    MongoMotor,
)
from env import *
from rich.console import Console
import urllib3
import atexit

urllib3.disable_warnings()

console = Console()
grpcclient = GRPCClient()
tooter = Tooter()

mongodb = MongoDB(tooter)
motormongo = MongoMotor(tooter)


def main():
    """
    The Hearbeat repo is an endless async loop of three methods:
    1. `get_finalized_blocks`: this method looks up the last processed block
    in a mongoDB helper collection, and determines how many finalized
    blocks it needs to request from the node. These blocks are then added
    to the queue `finalized_block_infos_to_process`.
    2. `process_blocks` picks up this queue of blocks to process, and
    continues processing until the queue is empty again. For every block,
    we store the block_info (including tx hashes) into the collection `blocks`.
    Furthermore, we inspect all transactions for a block to determine whether we need
    to create any indices for them.
    3. `send_to_mongo`: this method takes all queues and sends them to the respective
    MongoDB collections.
    """
    console.log(f"{RUN_ON_NET=}")
    grpcclient = GRPCClient()

    heartbeat = Heartbeat(grpcclient, tooter, mongodb, motormongo, RUN_ON_NET)
    atexit.register(heartbeat.exit)
    # these to helper methods are not needed, only things
    # go really wrong...

    # heartbeat.create_mongodb_indices()

    # heartbeat.create_block_per_day()

    loop = asyncio.get_event_loop()

    loop.create_task(heartbeat.get_finalized_blocks())
    loop.create_task(heartbeat.process_blocks())
    loop.create_task(heartbeat.send_to_mongo())

    loop.create_task(heartbeat.update_token_accounting())

    loop.create_task(heartbeat.get_special_purpose_blocks())
    loop.create_task(heartbeat.process_special_purpose_blocks())

    loop.create_task(heartbeat.get_redo_token_addresses())
    loop.create_task(heartbeat.special_purpose_token_accounting())

    loop.run_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception as f:
        console.log("main error: ", f)
