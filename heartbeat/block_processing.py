# ruff: noqa: F403, F405, E402, E501, E722
from .utils import Queue
from .module_logic import ModuleLogic as _module_logic
from .impacted_addresses import ImpactedAddresses as _impacted_addresses
from rich.progress import track
from ccdefundamentals.GRPCClient import GRPCClient
from ccdefundamentals.GRPCClient.CCD_Types import *
from ccdefundamentals.tooter import TooterChannel, TooterType
from ccdefundamentals.mongodb import Collections
from ccdefundamentals.enums import NET
from pymongo import ReplaceOne
from pymongo.collection import Collection
from env import *
import asyncio
import json
from rich.console import Console

console = Console()


class ClassificationResult:
    """
    This is a result type to store the classification of a transaction,
    used to determine which indices, if any, need to be created for this
    transaction.
    """

    def __init__(self):
        self.sender = None
        self.receiver = None
        self.tx_hash = None
        self.memo = None
        self.contract = None
        self.amount = None
        self.type = None
        self.contents = None
        self.accounts_involved_all = False
        self.accounts_involved_transfer = False
        self.contracts_involved = False
        self.module_involved = False
        self.actual_module_involved = None
        self.list_of_contracts_involved = []


class AccountTransactionOutcome(Enum):
    Success = "success"
    Failure = "failure"


class BlockProcessing(_module_logic, _impacted_addresses):

    def lookout_for_end_of_day(self, current_block_to_process: CCD_BlockInfo):
        end_of_day_timeframe_start = dt.time(0, 0, 0)
        end_of_day_timeframe_end = dt.time(0, 2, 0)

        if (
            current_block_to_process.slot_time.time() >= end_of_day_timeframe_start
        ) and (current_block_to_process.slot_time.time() <= end_of_day_timeframe_end):
            previous_block_height = current_block_to_process.height - 1
            previous_block_info = self.grpcclient.get_finalized_block_at_height(
                previous_block_height, NET(self.net)
            )

            if (
                current_block_to_process.slot_time.day
                != previous_block_info.slot_time.day
            ):
                start_of_day0 = previous_block_info.slot_time.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                start_of_day1 = previous_block_info.slot_time.replace(
                    hour=0, minute=1, second=59, microsecond=999999
                )

                start_of_day_blocks = list(
                    self.db[Collections.blocks].find(
                        filter={
                            "$and": [
                                {"slot_time": {"$gte": start_of_day0}},
                                {"slot_time": {"$lte": start_of_day1}},
                            ]
                        }
                    )
                )

                if len(start_of_day_blocks) == 0:
                    start_of_day_blocks = [
                        self.grpcclient.get_finalized_block_at_height(0, NET(self.net))
                    ]
                    self.add_end_of_day_to_queue(
                        f"{previous_block_info.slot_time:%Y-%m-%d}",
                        start_of_day_blocks[0],
                        previous_block_info,
                    )
                else:
                    self.add_end_of_day_to_queue(
                        f"{previous_block_info.slot_time:%Y-%m-%d}",
                        CCD_BlockInfo(**start_of_day_blocks[0]),
                        previous_block_info,
                    )
                console.log(
                    f"End of day found for {previous_block_info.slot_time:%Y-%m-%d}"
                )

    def lookout_for_payday(self, current_block_to_process: CCD_BlockInfo):
        payday_timeframe_start = dt.time(8, 55, 0)
        payday_timeframe_end = dt.time(9, 10, 0)

        if (current_block_to_process.slot_time.time() > payday_timeframe_start) and (
            current_block_to_process.slot_time.time() < payday_timeframe_end
        ):
            special_events = self.grpcclient.get_block_special_events(
                current_block_to_process.hash, NET(self.net)
            )
            found = False
            for se in special_events:
                if se.payday_account_reward or se.payday_pool_reward:
                    found = True
                    # this is a special case/place to already log the last_processed message
                    # as this is holding up the bot v2 in processing the payday block.
                    self.log_last_processed_message_in_mongo(current_block_to_process)
                    # protection for slow payday calculation
                    # first get the current date that we have stored
                    # as last known payday.
                    # Then check if this date has already been picked up
                    # by the payday calculation by checking if there
                    # exists a payday with that date.

                    # TODO: when we need to rerun EVERYTING, comment out the below....

                    # payday_not_yet_processed = True
                    # while payday_not_yet_processed:
                    #     last_known_payday = self.db[Collections.helpers].find_one(
                    #         {"_id": "last_known_payday"}
                    #     )
                    #     # if we haven't started with the first payday
                    #     # we can continue.
                    #     if not last_known_payday:
                    #         payday_not_yet_processed = False
                    #         result = True
                    #     else:
                    #         result = self.db[Collections.paydays].find_one(
                    #             {"date": last_known_payday["date"]}
                    #         )
                    #     if not result:
                    #         console.log(
                    #             f"Payday {last_known_payday['date']} not yet processed. Sleeping for 10 sec."
                    #         )
                    #         time.sleep(10)
                    #     else:
                    #         payday_not_yet_processed = False

                    new_payday_date_string = (
                        f"{current_block_to_process.slot_time:%Y-%m-%d}"
                    )

                    query = {"_id": "last_known_payday"}
                    self.db[Collections.helpers].replace_one(
                        query,
                        {
                            "_id": "last_known_payday",
                            "date": new_payday_date_string,
                            "hash": current_block_to_process.hash,
                            "height": current_block_to_process.height,
                        },
                        upsert=True,
                    )
            if found:
                console.log(
                    f"Payday {current_block_to_process.slot_time:%Y-%m-%d} found!"
                )
                # time.sleep(90)

    def classify_transaction(self, tx: CCD_BlockItemSummary):
        """
        This classifies a transaction (based on GRPCv2 output)
        for inclusion in the index tables.
        """
        result = ClassificationResult()
        result.type = tx.type

        if tx.account_creation:
            result.sender = tx.account_creation.address

        if tx.account_transaction:
            result.sender = tx.account_transaction.sender

            if (
                tx.account_transaction.outcome
                == AccountTransactionOutcome.Success.value
            ):
                effects = tx.account_transaction.effects

                if effects.account_transfer:
                    result.accounts_involved_transfer = True

                    ac = effects.account_transfer
                    result.amount = ac.amount
                    result.receiver = ac.receiver
                    if ac.memo:
                        result.memo = ac.memo

                elif effects.transferred_with_schedule:
                    result.accounts_involved_transfer = True

                    ts = effects.transferred_with_schedule
                    result.amount = self.get_sum_amount_from_scheduled_transfer(
                        ts.amount
                    )
                    result.receiver = ts.receiver
                    if ts.memo:
                        result.memo = ts.memo

                elif effects.contract_initialized:
                    result.contracts_involved = True

                    ci = effects.contract_initialized
                    result.list_of_contracts_involved.append({"address": ci.address})

                elif effects.module_deployed:
                    result.module_involved = True
                    result.actual_module_involved = effects.module_deployed

                elif effects.contract_update_issued:
                    result.contracts_involved = True

                    update_effects = effects.contract_update_issued.effects

                    for effect in update_effects:
                        if effect.interrupted:
                            result.list_of_contracts_involved.append(
                                {"address": effect.interrupted.address}
                            )

                        elif effect.resumed:
                            result.list_of_contracts_involved.append(
                                {"address": effect.resumed.address}
                            )

                        elif effect.updated:
                            result.list_of_contracts_involved.append(
                                {
                                    "address": effect.updated.address,
                                    "receive_name": effect.updated.receive_name,
                                }
                            )

                        elif effect.transferred:
                            if type(effect.transferred.sender) == CCD_ContractAddress:
                                result.list_of_contracts_involved.append(
                                    {"address": effect.transferred.sender}
                                )

                            if type(effect.transferred.receiver) == CCD_ContractAddress:
                                result.list_of_contracts_involved.append(
                                    {"address": effect.transferred.receiver}
                                )

        return result

    def index_transfer_and_all(
        self,
        tx: CCD_BlockItemSummary,
        result: ClassificationResult,
        block_info: CCD_BlockInfo,
    ):
        dct_transfer_and_all = {
            "_id": tx.hash,
            "sender": result.sender,
            "receiver": result.receiver,
            "sender_canonical": result.sender[:29] if result.sender else None,
            "receiver_canonical": result.receiver[:29] if result.receiver else None,
            "amount": result.amount,
            "type": result.type.model_dump(),
            "block_height": block_info.height,
        }
        if result.memo:
            dct_transfer_and_all.update({"memo": result.memo})

        return dct_transfer_and_all

    def index_contract(
        self,
        tx: CCD_BlockItemSummary,
        result: ClassificationResult,
        contract: CCD_ContractAddress,
        block_info: CCD_BlockInfo,
    ):
        _id = f"{tx.hash}-<{contract.index},{contract.subindex}>"
        dct = {
            "_id": _id,
            "index": contract.index,
            "subindex": contract.subindex,
            "contract": f"<{contract.index},{contract.subindex}>",
            "type": result.type.model_dump(),
            "block_height": block_info.height,
        }

        return dct

    def generate_indices_based_on_transactions(
        self,
        transactions: list[CCD_BlockItemSummary],
        block_info: CCD_BlockInfo,
        special_purpose: bool = False,
    ):
        """
        Given a list of transactions, apply rules to determine which index needs to be updated.
        Add this to a to_be_sent_to_mongo list and do insert_many.
        """
        self.queues: dict[Collections, list]
        self.db: dict[Collections, Collection]
        self.existing_source_modules: dict[CCD_ModuleRef, set]
        self.existing_instances: dict[str, CCD_ModuleRef]
        self.grpcclient: GRPCClient
        # decode = 0
        # extract = 0
        # classify = 0
        # index_transfer = 0
        # smart_c = 0
        cis_2_contracts = {}
        for tx in transactions:
            # s = dt.datetime.now()
            (
                logged_events,
                token_addresses_to_redo_accounting,
                provenance_contracts_to_add,
                cis_2_contracts,
            ) = self.decode_cis_logged_events(
                tx, block_info, cis_2_contracts, special_purpose
            )
            # decode += (dt.datetime.now() - s).total_seconds()

            if len(logged_events) > 0:
                self.queues[Queue.logged_events].extend(logged_events)

            if len(token_addresses_to_redo_accounting) > 0:
                self.queues[Queue.token_addresses_to_redo_accounting].extend(
                    token_addresses_to_redo_accounting
                )

            if len(provenance_contracts_to_add) > 0:
                self.queues[Queue.provenance_contracts_to_add].extend(
                    provenance_contracts_to_add
                )

            tx.block_info = CCD_ShortBlockInfo(
                height=block_info.height,
                hash=block_info.hash,
                slot_time=block_info.slot_time,
            )
            # s = dt.datetime.now()
            self.extract_impacted_addesses_from_tx(tx)
            # extract += (dt.datetime.now() - s).total_seconds()

            # s = dt.datetime.now()
            result = self.classify_transaction(tx)
            # classify += (dt.datetime.now() - s).total_seconds()

            # s = dt.datetime.now()
            dct_transfer_and_all = self.index_transfer_and_all(tx, result, block_info)
            # index_transfer += (dt.datetime.now() - s).total_seconds()
            # always store tx in this collection
            self.queues[Queue.involved_all].append(
                ReplaceOne(
                    {"_id": dct_transfer_and_all["_id"]},
                    dct_transfer_and_all,
                    upsert=True,
                )
            )

            if result.module_involved:
                self.get_module_data_and_add_to_queue(result.actual_module_involved)

            # only store tx in this collection if it's a transfer
            if result.accounts_involved_transfer:
                self.queues[Queue.involved_transfer].append(
                    ReplaceOne(
                        {"_id": dct_transfer_and_all["_id"]},
                        dct_transfer_and_all,
                        upsert=True,
                    )
                )

            # only store tx in this collection if it contains a smart contract
            # s = dt.datetime.now()
            if result.contracts_involved:
                for contract in result.list_of_contracts_involved:
                    index_contract = self.index_contract(
                        tx, result, contract["address"], block_info
                    )

                    try:
                        if index_contract["contract"] not in self.existing_instances:
                            instance_info = self.grpcclient.get_instance_info(
                                index_contract["index"],
                                index_contract["subindex"],
                                block_info.hash,
                                NET(self.net),
                            )
                            instance_info: dict = instance_info.model_dump(
                                exclude_none=True
                            )

                            instance_info.update({"_id": index_contract["contract"]})
                            if instance_info["v0"]["source_module"] == "":
                                del instance_info["v0"]
                                _source_module = instance_info["v1"]["source_module"]
                            if instance_info["v1"]["source_module"] == "":
                                del instance_info["v1"]
                                _source_module = instance_info["v0"]["source_module"]

                            self.queues[Queue.instances].append(
                                ReplaceOne(
                                    {"_id": index_contract["contract"]},
                                    instance_info,
                                    upsert=True,
                                )
                            )

                            if (
                                _source_module
                                not in self.existing_source_modules.keys()
                            ):
                                self.existing_source_modules[_source_module] = set()

                            self.existing_source_modules[_source_module].add(
                                index_contract["contract"]
                            )
                            self.queues[Queue.updated_modules].append(_source_module)

                            index_contract.update({"source_module": _source_module})

                            self.queues[Queue.involved_contract].append(
                                ReplaceOne(
                                    {"_id": index_contract["_id"]},
                                    index_contract,
                                    upsert=True,
                                )
                            )
                    except:
                        console.log(
                            f"block or instance not found for {index_contract}..."
                        )

        #     smart_c += (dt.datetime.now() - s).total_seconds()

        # console.log(f"{decode=:,.4} s")
        # console.log(f"{extract=:,.4} s")
        # console.log(f"{classify=:,.4} s")
        # console.log(f"{index_transfer=:,.4} s")
        # console.log(f"{smart_c=:,.4} s")

    def add_block_and_txs_to_queue(
        self, block_info: CCD_BlockInfo, special_purpose: bool = False
    ):
        try:
            json_block_info: dict = json.loads(
                block_info.model_dump_json(exclude_none=True)
            )
        except Exception as e:
            print(e)
        json_block_info.update({"_id": block_info.hash})
        json_block_info.update({"slot_time": block_info.slot_time})
        del json_block_info["arrive_time"]
        del json_block_info["receive_time"]
        json_block_info.update({"transaction_hashes": []})

        if block_info.transaction_count > 0:
            # console.log(block_info.height)
            # s = dt.datetime.now()
            block: CCD_Block = self.grpcclient.get_block_transaction_events(
                block_info.hash, NET(self.net)
            )

            json_block_info.update(
                {"transaction_hashes": [x.hash for x in block.transaction_summaries]}
            )

            for tx in block.transaction_summaries:
                json_tx: dict = json.loads(tx.model_dump_json(exclude_none=True))

                json_tx.update({"_id": tx.hash})
                json_tx.update(
                    {
                        "block_info": {
                            "height": block_info.height,
                            "hash": block_info.hash,
                            "slot_time": block_info.slot_time,
                        }
                    }
                )
                self.queues[Queue.transactions].append(
                    ReplaceOne({"_id": tx.hash}, replacement=json_tx, upsert=True)
                )
                # self.lookout_for_account_transaction(block_info, tx)
            # console.log(
            #     f"get_block_transaction_events: {(dt.datetime.now()-s).total_seconds():,.4} s for {block_info.transaction_count} txs."
            # )
            # s = dt.datetime.now()
            self.generate_indices_based_on_transactions(
                block.transaction_summaries, block_info, special_purpose
            )
            # console.log(
            #     f"generate_indices_based_on_transactions: {(dt.datetime.now()-s).total_seconds():,.4} s for {block_info.transaction_count} txs."
            # )
        self.queues[Queue.blocks].append(
            ReplaceOne(
                {"_id": block_info.hash}, replacement=json_block_info, upsert=True
            )
        )
        self.queues[Queue.block_heights].append(block_info.height)

        # add special events
        se = self.grpcclient.get_block_special_events(block_info.height)
        se_list = [x.model_dump(exclude_none=True) for x in se]

        d = {"_id": block_info.height, "special_events": se_list}
        self.queues[Queue.special_events].append(
            ReplaceOne(
                {"_id": block_info.height},
                replacement=d,
                upsert=True,
            )
        )
