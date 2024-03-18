# ruff: noqa: F403, F405, E402, E501, E722
from ccdefundamentals.GRPCClient import GRPCClient
from ccdefundamentals.GRPCClient.CCD_Types import *
from ccdefundamentals.tooter import Tooter
from ccdefundamentals.mongodb import (
    MongoDB,
    Collections,
    MongoMotor,
)

from pymongo.collection import Collection
from env import *
from rich.console import Console
import urllib3

from .impacted_addresses import ImpactedAddresses as _impacted_addresses
from .token_accounting import TokenAccounting as _token_accounting
from .start_over import StartOver as _start_over
from .send_to_mongo import SendToMongo as _send_to_mongo
from .block_loop import BlockLoop as _block_loop
from .consistency import Consistency as _consistency
from .utils import Queue
import aiohttp

urllib3.disable_warnings()
console = Console()


class Heartbeat(
    _block_loop,
    _impacted_addresses,
    _token_accounting,
    _start_over,
    _send_to_mongo,
    _consistency,
):
    def __init__(
        self,
        grpcclient: GRPCClient,
        tooter: Tooter,
        mongodb: MongoDB,
        motormongo: MongoMotor,
        net: str,
    ):
        self.grpcclient = grpcclient
        self.tooter = tooter
        self.mongodb = mongodb
        self.motormongo = motormongo
        self.net = net
        self.utilities: dict[Collections, Collection] = self.mongodb.utilities
        self.db: dict[Collections, Collection] = (
            self.mongodb.mainnet if self.net == "mainnet" else self.mongodb.testnet
        )
        self.motordb: dict[Collections, Collection] = (
            self.motormongo.testnet if net == "testnet" else self.motormongo.mainnet
        )
        self.finalized_block_infos_to_process: list[CCD_BlockInfo] = []
        self.special_purpose_block_infos_to_process: list[CCD_BlockInfo] = []

        self.existing_source_modules: dict[CCD_ModuleRef, set] = {}
        self.queues: dict[Collections, list] = {}
        for q in Queue:
            self.queues[q] = []

        # this gets set every time the log heartbeat last processed helper gets set
        # in block_loop we check if this value is < x min from now.
        # If so, we restart, as there's probably something wrong that a restart
        # can fix.
        self.internal_freqency_timer = dt.datetime.now().astimezone(tz=dt.timezone.utc)
        self.session = aiohttp.ClientSession()
        coin_api_headers = {
            "X-CoinAPI-Key": COIN_API_KEY,
        }
        self.coin_api_session = aiohttp.ClientSession(headers=coin_api_headers)

    def exit(self):
        self.session.close()
        self.coin_api_session.close()
