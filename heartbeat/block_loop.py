# ruff: noqa: F403, F405, E402, E501, E722
from .utils import Queue
from .block_processing import BlockProcessing as _block_processing
from ccdefundamentals.tooter import TooterChannel, TooterType
from ccdefundamentals.mongodb import Collections
from ccdefundamentals.GRPCClient.CCD_Types import *
from pymongo import ReplaceOne
from pymongo.collection import Collection
from ccdefundamentals.enums import NET
from env import *
import datetime as dt
from copy import copy

import asyncio
from rich.console import Console

console = Console()


class BlockLoop(_block_processing):
    def process_list_of_blocks(self, block_list: list, special_purpose: bool = False):
        self.queues: dict[Collections, list]
        self.db: dict[Collections, Collection]
        result = self.db[Collections.modules].find({})
        result = list(result)
        self.existing_source_modules: dict[CCD_ModuleRef, set] = {
            x["_id"]: set(x["contracts"]) for x in result if x["contracts"] is not None
        }
        existing_source_modules_no_contracts = {
            x["_id"]: set() for x in result if x["contracts"] is None
        }
        self.existing_source_modules.update(existing_source_modules_no_contracts)
        self.queues[Queue.updated_modules] = []

        result = self.db[Collections.instances].find({})
        result = list(result)
        self.existing_instances: dict[str, CCD_ModuleRef] = {
            x["_id"]: True for x in result
        }

        start = dt.datetime.now()
        while len(block_list) > 0:
            current_block_to_process: CCD_BlockInfo = block_list.pop(0)
            try:
                self.add_block_and_txs_to_queue(
                    current_block_to_process, special_purpose
                )

                self.lookout_for_payday(current_block_to_process)
                self.lookout_for_end_of_day(current_block_to_process)

                if special_purpose:
                    # if it's a special purpose block, we need to remove it from the helper
                    result: dict = self.db[Collections.helpers].find_one(
                        {"_id": "special_purpose_block_request"}
                    )
                    if result:
                        heights: list = result["heights"]
                        try:
                            heights.remove(current_block_to_process.height)
                        except ValueError:
                            console.log(
                                f" Tried 'heights.remove(current_block_to_process.height)' for {current_block_to_process.height:,.0f} but failed."
                            )
                        result.update({"heights": heights})
                    _ = self.db[Collections.helpers].bulk_write(
                        [
                            ReplaceOne(
                                {"_id": "special_purpose_block_request"},
                                replacement=result,
                                upsert=True,
                            )
                        ]
                    )
            except Exception as e:
                self.log_error_in_mongo(e, current_block_to_process)
        duration = dt.datetime.now() - start
        console.log(
            f"Spent {duration.total_seconds():,.0f} sec on {len(self.queues[Queue.transactions]):,.0f} txs."
        )

        if len(self.queues[Queue.instances]) > 0:
            self.add_back_updated_modules_to_queue(current_block_to_process)

        return current_block_to_process

    async def process_blocks(self):
        """
        This method takes the queue `finalized_block_infos_to_process` and processes
        each block.
        """
        self.finalized_block_infos_to_process: list[CCD_BlockInfo]
        while True:
            if len(self.finalized_block_infos_to_process) > 0:
                pp = copy(self.finalized_block_infos_to_process)
                # this is the last block that was processed
                current_block_to_process = self.process_list_of_blocks(
                    self.finalized_block_infos_to_process
                )

                self.log_last_processed_message_in_mongo(current_block_to_process)
                if len(pp) == 1:
                    console.log(f"Block processed: {pp[0].height:,.0f}")
                else:
                    console.log(
                        f"Blocks processed: {pp[0].height:,.0f} - {pp[-1].height:,.0f}"
                    )
            await asyncio.sleep(1)

    async def process_special_purpose_blocks(self):
        """
        This method takes the queue `special_purpose_block_infos_to_process` and processes
        each block.
        """
        self.special_purpose_block_infos_to_process: list[CCD_BlockInfo]
        while True:
            if len(self.special_purpose_block_infos_to_process) > 0:
                pp = copy(self.special_purpose_block_infos_to_process)
                # this is the last block that was processed

                _ = self.process_list_of_blocks(
                    self.special_purpose_block_infos_to_process, special_purpose=True
                )

                if len(pp) == 1:
                    console.log(f"SP Block processed: {pp[0].height:,.0f}")
                else:
                    console.log(
                        f"SP Blocks processed: {pp[0].height:,.0f} - {pp[-1].height:,.0f}"
                    )
            await asyncio.sleep(5)

    async def get_special_purpose_blocks(self):
        """
        This methods gets special purpose blocks from the chosen net.
        It batches blocks up to MAX_BLOCKS_PER_RUN and stores blocks to be
        processed in the queue `finalized_block_infos_to_process`.
        """
        while True:
            result = self.db[Collections.helpers].find_one(
                {"_id": "special_purpose_block_request"}
            )
            if result:
                for height in result["heights"]:
                    self.special_purpose_block_infos_to_process.append(
                        self.grpcclient.get_finalized_block_at_height(
                            int(height), NET(self.net)
                        )
                    )

            await asyncio.sleep(10)

    async def get_finalized_blocks(self):
        """
        This methods gets finalized blocks from the chosen net.
        It batches blocks up to MAX_BLOCKS_PER_RUN and stores blocks to be
        processed in the queue `finalized_block_infos_to_process`.
        """
        if DEBUG:
            console.log("get_finalized_blocks")
        while True:
            # this comparison makes sure that if we haven't logged a new block in 5 min
            # something somewhere has gone wrong. Hoping that a restart will fix things...
            current_time = dt.datetime.now().astimezone(tz=dt.timezone.utc)
            if (current_time - self.internal_freqency_timer).total_seconds() > 5 * 60:
                self.tooter.relay(
                    channel=TooterChannel.NOTIFIER,
                    title="",
                    chat_id=ADMIN_CHAT_ID,
                    body=f"Heartbeat on {self.net} seems to not have processed a new block in 5 min? Exiting to restart.",
                    notifier_type=TooterType.REQUESTS_ERROR,
                )
                exit()

            request_counter = 0
            result = self.db[Collections.helpers].find_one(
                {"_id": "heartbeat_last_processed_block"}
            )
            heartbeat_last_processed_block_height = result["height"]
            if DEBUG:
                console.log(f"{heartbeat_last_processed_block_height=}")
            last_requested_block_not_finalized = False
            block_to_request_in_queue = False

            while (
                not (last_requested_block_not_finalized)
                and (request_counter < MAX_BLOCKS_PER_RUN)
                and not block_to_request_in_queue
            ):
                request_counter += 1

                # increment the block height to request
                heartbeat_last_processed_block_height += 1

                # check to see if we haven't finished processing the queue
                # If so, no need to request and add the same block again.
                block_to_request_in_queue = heartbeat_last_processed_block_height in [
                    x.height for x in self.finalized_block_infos_to_process
                ]
                if DEBUG:
                    console.log(f"{self.finalized_block_infos_to_process=}")
                # we haven't previously requested this block
                if not block_to_request_in_queue:
                    try:
                        finalized_block_info_at_height = (
                            self.grpcclient.get_finalized_block_at_height(
                                heartbeat_last_processed_block_height, NET(self.net)
                            )
                        )
                    except:
                        finalized_block_info_at_height = False

                    if finalized_block_info_at_height:
                        self.finalized_block_infos_to_process.append(
                            finalized_block_info_at_height
                        )
                    else:
                        last_requested_block_not_finalized = True
            if DEBUG:
                console.log(f"{len(self.finalized_block_infos_to_process)=}")
            if len(self.finalized_block_infos_to_process) > 0:
                if len(self.finalized_block_infos_to_process) == 1:
                    console.log(
                        f"Block retrieved: {self.finalized_block_infos_to_process[0].height:,.0f}"
                    )
                else:
                    console.log(
                        f"Blocks retrieved: {self.finalized_block_infos_to_process[0].height:,.0f} - {self.finalized_block_infos_to_process[-1].height:,.0f}"
                    )
                    if (
                        self.finalized_block_infos_to_process[0].height
                        > self.finalized_block_infos_to_process[-1].height
                    ):
                        self.tooter.relay(
                            channel=TooterChannel.NOTIFIER,
                            title="",
                            chat_id=ADMIN_CHAT_ID,
                            body=f"Heartbeat on {self.net} seems to be in a loop? Exiting to restart.",
                            notifier_type=TooterType.REQUESTS_ERROR,
                        )
                        exit()
            await asyncio.sleep(1)
