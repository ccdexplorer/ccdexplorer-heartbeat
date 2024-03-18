# ruff: noqa: F403, F405, E402, E501, E722
from .utils import Utils
from ccdefundamentals.mongodb import Collections
from ccdefundamentals.tooter import TooterChannel, TooterType

from pymongo.collection import Collection
from pymongo import ReplaceOne
from env import *
import asyncio
from rich.console import Console
import random

console = Console()


class Consistency(Utils):
    async def check_blocks(self):
        self.db: dict[Collections, Collection]
        self.motordb: dict[Collections, Collection]
        sample_size = 1_000
        while True:
            try:
                result = self.db[Collections.helpers].find_one(
                    {"_id": "heartbeat_last_processed_block"}
                )
                heartbeat_last_processed_block = result["height"]
                random_block_list = random.sample(
                    range(1, heartbeat_last_processed_block), sample_size
                )

                count_documents_in_collection = await self.motordb[
                    Collections.blocks
                ].count_documents({"height": {"$in": random_block_list}})

                # print()
                if count_documents_in_collection == sample_size:
                    pass
                else:

                    documents = (
                        await self.motordb[Collections.blocks]
                        .aggregate(
                            [
                                {"$match": {"height": {"$in": random_block_list}}},
                                {
                                    "$project": {
                                        "_id": 0,
                                        "height": 1,
                                    }
                                },
                            ]
                        )
                        .to_list(1_000_000_000)
                    )
                    found_documents = [x["height"] for x in documents]
                    missing_blocks = []
                    for random_block in random_block_list:
                        if random_block not in found_documents:
                            missing_blocks.append(random_block)
                    print(f"{len(missing_blocks):,.0f} missing blocks on {self.net}.")

                    d = {
                        "_id": "special_purpose_block_request",
                        "heights": missing_blocks,
                    }
                    _ = self.db[Collections.helpers].bulk_write(
                        [
                            ReplaceOne(
                                {"_id": "special_purpose_block_request"},
                                replacement=d,
                                upsert=True,
                            )
                        ]
                    )

                    self.tooter.relay(
                        channel=TooterChannel.NOTIFIER,
                        title="",
                        chat_id=ADMIN_CHAT_ID,
                        body=f"Heartbeat: Heartbeat on {self.net} missed {len(missing_blocks):,.0f} blocks. {'Added as special request.' if len(missing_blocks) > 0 else ''}\n{' '.join([x for x in missing_blocks])}",
                        notifier_type=TooterType.INFO,
                    )
            except Exception as e:
                console.log(e)

            await asyncio.sleep(60)

    async def check_transactions(self):
        self.db: dict[Collections, Collection]
        self.motordb: dict[Collections, Collection]
        while True:
            try:
                result = (
                    await self.motordb[Collections.blocks]
                    .aggregate(
                        [
                            {"$sample": {"size": 1000}},
                            {
                                "$project": {
                                    "_id": 0,
                                    "transaction_hashes": 1,
                                    "height": 1,
                                }
                            },
                        ],
                    )
                    .to_list(1_000_000_000)
                )

                all_tx_hashes_from_blocks_in_db = [
                    x["transaction_hashes"] for x in result
                ]

                all_tx_hashes_from_blocks_in_db_dict = {}
                for r in result:
                    for tx_hash in r["transaction_hashes"]:
                        all_tx_hashes_from_blocks_in_db_dict[tx_hash] = r["height"]

                # all_tx_hashes_from_blocks_in_db = [
                #     item
                #     for sublist in all_tx_hashes_from_blocks_in_db
                #     for item in sublist
                # ]

                result_tx = (
                    await self.motordb[Collections.transactions]
                    .aggregate(
                        [
                            {
                                "$match": {
                                    "_id": {
                                        "$nin": list(
                                            all_tx_hashes_from_blocks_in_db_dict.keys()
                                        )
                                    }
                                }
                            },
                            {"$project": {"_id": 1}},
                        ],
                    )
                    .to_list(1_000_000_000)
                )

                all_tx_hashes_from_transactions_in_db = [x["_id"] for x in result_tx]

                missing_txs = len(all_tx_hashes_from_blocks_in_db) - len(
                    all_tx_hashes_from_transactions_in_db
                )
                print(f"{len(missing_txs):,.0f} missing transactions on {self.net}.")
                # print(missing_txs)

                missing_heights = []
                for tx_hash in missing_txs:
                    missing_heights.append(
                        all_tx_hashes_from_blocks_in_db_dict[tx_hash]
                    )

                missing_heights = list(set(missing_heights))
                # print(missing_heights)

                d = {"_id": "special_purpose_block_request", "heights": missing_heights}
                _ = self.db[Collections.helpers].bulk_write(
                    [
                        ReplaceOne(
                            {"_id": "special_purpose_block_request"},
                            replacement=d,
                            upsert=True,
                        )
                    ]
                )

                self.tooter.relay(
                    channel=TooterChannel.NOTIFIER,
                    title="",
                    chat_id=ADMIN_CHAT_ID,
                    body=f"Heartbeat on {self.net} missed {len(missing_txs):,.0f} transactions in {len(missing_heights):,.0f} blocks. Added as special request.",
                    notifier_type=TooterType.INFO,
                )
            except Exception as e:
                console.log(e)

            await asyncio.sleep(120 * 60)
