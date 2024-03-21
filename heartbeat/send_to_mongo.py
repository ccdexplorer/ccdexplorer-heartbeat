# ruff: noqa: F403, F405, E402, E501, E722
from .utils import Utils, Queue
from ccdexplorer_fundamentals.mongodb import Collections
from ccdexplorer_fundamentals.tooter import TooterChannel, TooterType

from pymongo.collection import Collection
from pymongo.results import BulkWriteResult
from env import *
import asyncio
from rich.console import Console

console = Console()


class SendToMongo(Utils):
    async def send_to_mongo(self):
        """
        This method takes all queues with mongoDB messages and sends them to the
        respective collections.
        """
        self.queues: dict[Collections, list]
        self.db: dict[Collections, Collection]
        self.motordb: dict[Collections, Collection]
        while True:
            try:
                if len(self.queues[Queue.blocks]) > 0:
                    result = self.db[Collections.blocks].bulk_write(
                        self.queues[Queue.blocks]
                    )
                    if len(self.queues[Queue.block_heights]) == 1:
                        console.log(
                            f"Sent to Mongo  : {self.queues[Queue.block_heights][0]:,.0f}"
                        )
                    else:
                        console.log(
                            f"Sent to Mongo   : {self.queues[Queue.block_heights][0]:,.0f} - {self.queues[Queue.block_heights][-1]:,.0f}"
                        )
                    console.log(
                        f"B:  {len(self.queues[Queue.blocks]):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )
                    self.queues[Queue.blocks] = []
                    self.queues[Queue.block_heights] = []
                else:
                    pass
                    # update_ = False

                if len(self.queues[Queue.special_events]) > 0:
                    result = self.db[Collections.special_events].bulk_write(
                        self.queues[Queue.special_events]
                    )
                    self.queues[Queue.special_events] = []

                if len(self.queues[Queue.transactions]) > 0:
                    tx_queue = self.queues[Queue.transactions]
                    self.queues[Queue.transactions] = []
                    result: BulkWriteResult = await self.motordb[
                        Collections.transactions
                    ].bulk_write(tx_queue)
                    console.log(
                        f"T:  {len(tx_queue):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )

                if len(self.queues[Queue.involved_all]) > 0:
                    ia_queue = self.queues[Queue.involved_all]
                    self.queues[Queue.involved_all] = []
                    result: BulkWriteResult = await self.motordb[
                        Collections.involved_accounts_all
                    ].bulk_write(ia_queue)
                    console.log(
                        f"A:  {len(ia_queue):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )
                    self.queues[Queue.involved_all] = []

                if len(self.queues[Queue.involved_transfer]) > 0:
                    result = self.db[Collections.involved_accounts_transfer].bulk_write(
                        self.queues[Queue.involved_transfer]
                    )
                    console.log(
                        f"Tr: {len(self.queues[Queue.involved_transfer]):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )
                    self.queues[Queue.involved_transfer] = []

                if len(self.queues[Queue.involved_contract]) > 0:
                    result = self.db[Collections.involved_contracts].bulk_write(
                        self.queues[Queue.involved_contract]
                    )
                    console.log(
                        f"C:  {len(self.queues[Queue.involved_contract]):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )
                    self.queues[Queue.involved_contract] = []

                if len(self.queues[Queue.instances]) > 0:
                    result = self.db[Collections.instances].bulk_write(
                        self.queues[Queue.instances]
                    )
                    console.log(
                        f"I:  {len(self.queues[Queue.instances]):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )
                    self.queues[Queue.instances] = []

                if len(self.queues[Queue.modules]) > 0:
                    result = self.db[Collections.modules].bulk_write(
                        self.queues[Queue.modules]
                    )
                    console.log(
                        f"M:  {len(self.queues[Queue.modules]):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )
                    self.queues[Queue.modules] = []

                if len(self.queues[Queue.block_per_day]) > 0:
                    result = self.db[Collections.blocks_per_day].bulk_write(
                        self.queues[Queue.block_per_day]
                    )
                    console.log(f"End of day: U {result.upserted_count:5,.0f}")
                    self.queues[Queue.block_per_day] = []

                if len(self.queues[Queue.logged_events]) > 0:
                    le_queue = self.queues[Queue.logged_events]
                    self.queues[Queue.logged_events] = []
                    result: BulkWriteResult = await self.motordb[
                        Collections.tokens_logged_events
                    ].bulk_write(le_queue)
                    console.log(
                        f"E:  {len(le_queue):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )

                if len(self.queues[Queue.impacted_addresses]) > 0:
                    ia_queue = self.queues[Queue.impacted_addresses]
                    self.queues[Queue.impacted_addresses] = []
                    result: BulkWriteResult = await self.motordb[
                        Collections.impacted_addresses
                    ].bulk_write(ia_queue)
                    console.log(
                        f"IA: {len(ia_queue):5,.0f} | M {result.matched_count:5,.0f} | Mod {result.modified_count:5,.0f} | U {result.upserted_count:5,.0f}"
                    )

                if len(self.queues[Queue.token_addresses_to_redo_accounting]) > 0:
                    query = {"_id": "redo_token_addresses"}
                    self.db[Collections.helpers].replace_one(
                        query,
                        {
                            "_id": "redo_token_addresses",
                            "token_addresses": list(
                                set(
                                    self.queues[
                                        Queue.token_addresses_to_redo_accounting
                                    ]
                                )
                            ),
                        },
                        upsert=True,
                    )
                    console.log(
                        f"Added {len(self.queues[Queue.token_addresses_to_redo_accounting]):,.0f} token_addresses to redo accounting."
                    )
                    self.queues[Queue.token_addresses_to_redo_accounting] = []

                if len(self.queues[Queue.provenance_contracts_to_add]) > 0:
                    query = {"_id": "provenance-tags"}
                    current_content = self.db[Collections.tokens_tags].find_one(query)
                    if not current_content:
                        current_content = {
                            "_id": "provenance-tags",
                            "contracts": [],
                            "token_type": "non-fungible",
                            "tag_template": True,
                            "single_use_token": False,
                        }
                    current_contracts: list = current_content["contracts"]
                    current_contracts.extend(
                        list(set(self.queues[Queue.provenance_contracts_to_add]))
                    )

                    current_contracts = list(set(current_contracts))
                    current_contracts.sort()
                    current_content.update({"contracts": current_contracts})
                    self.db[Collections.tokens_tags].replace_one(
                        query,
                        replacement=current_content,
                        upsert=True,
                    )
                    console.log(
                        f"Added {len(list(set(self.queues[Queue.provenance_contracts_to_add]))):,.0f} contracts to provenance for {self.net}."
                    )
                    self.tooter.send(
                        channel=TooterChannel.NOTIFIER,
                        message=f"Added {' | '.join(list(set(self.queues[Queue.provenance_contracts_to_add])))} contracts to provenance-tags for {self.net}.",
                        notifier_type=TooterType.REQUESTS_ERROR,
                    )
                    self.queues[Queue.provenance_contracts_to_add] = []
                # this will only be set if the above store methods do not fail.

            except Exception as e:
                # pass
                console.log(e)
                self.tooter.relay(
                    channel=TooterChannel.NOTIFIER,
                    title="",
                    chat_id=ADMIN_CHAT_ID,
                    body=f"Heartbeat on {self.net} send_to_mongo: {e}",
                    notifier_type=TooterType.MONGODB_ERROR,
                )

            await asyncio.sleep(1)
