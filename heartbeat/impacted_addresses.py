# ruff: noqa: F403, F405, E402, E501, E722
from .utils import Utils, Queue
from ccdefundamentals.GRPCClient.CCD_Types import *
from ccdefundamentals.mongodb import (
    Collections,
    MongoImpactedAddress,
    AccountStatementEntryType,
    AccountStatementTransferType,
)
from pymongo import ReplaceOne


########### Impacted Addresses
class ImpactedAddresses(Utils):
    def file_a_balance_movement(
        self,
        tx: CCD_BlockItemSummary,
        impacted_addresses_in_tx: dict[str:MongoImpactedAddress],
        impacted_address: str,
        balance_movement_to_add: AccountStatementEntryType,
    ):
        if impacted_addresses_in_tx.get(impacted_address):
            impacted_address_as_class: MongoImpactedAddress = impacted_addresses_in_tx[
                impacted_address
            ]
            bm: AccountStatementEntryType = impacted_address_as_class.balance_movement
            if not bm:
                bm = AccountStatementEntryType()
            if balance_movement_to_add:
                field_set = list(balance_movement_to_add.model_fields_set)[0]

                if field_set in [
                    "transfer_in",
                    "transfer_out",
                    "amount_encrypted",
                    "amount_decrypted",
                ]:
                    impacted_address_as_class.included_in_flow = True

                if field_set == "transfer_in":
                    if not bm.transfer_in:
                        bm.transfer_in = []
                    bm.transfer_in.extend(balance_movement_to_add.transfer_in)
                elif field_set == "transfer_out":
                    if not bm.transfer_out:
                        bm.transfer_out = []
                    bm.transfer_out.extend(balance_movement_to_add.transfer_out)
                elif field_set == "amount_encrypted":
                    bm.amount_encrypted = balance_movement_to_add.amount_encrypted
                elif field_set == "amount_decrypted":
                    bm.amount_decrypted = balance_movement_to_add.amount_decrypted
                elif field_set == "baker_reward":
                    bm.baker_reward = balance_movement_to_add.baker_reward
                elif field_set == "finalization_reward":
                    bm.finalization_reward = balance_movement_to_add.finalization_reward
                elif field_set == "foundation_reward":
                    bm.foundation_reward = balance_movement_to_add.foundation_reward
                elif field_set == "transaction_fee_reward":
                    bm.transaction_fee_reward = (
                        balance_movement_to_add.transaction_fee_reward
                    )

            impacted_address_as_class.balance_movement = bm
        else:
            # new address
            included_in_flow = False
            if balance_movement_to_add:
                model_fields_set = list(balance_movement_to_add.model_fields_set)
                if len(model_fields_set) > 0:
                    field_set = model_fields_set[0]
                    if field_set in [
                        "transfer_in",
                        "transfer_out",
                        "amount_encrypted",
                        "amount_decrypted",
                    ]:
                        included_in_flow = True

            impacted_address_as_class = MongoImpactedAddress(
                **{
                    "_id": f"{tx.hash}-{impacted_address[:29]}",
                    # "_id": ObjectId(),
                    "tx_hash": tx.hash,
                    "impacted_address": impacted_address,
                    "impacted_address_canonical": impacted_address[:29],
                    "effect_type": tx.type.contents,
                    "balance_movement": balance_movement_to_add,
                    "block_height": tx.block_info.height,
                    "included_in_flow": included_in_flow,
                    "date": f"{tx.block_info.slot_time:%Y-%m-%d}",
                }
            )
            impacted_addresses_in_tx[impacted_address] = impacted_address_as_class

    def file_balance_movements(
        self,
        tx: CCD_BlockItemSummary,
        impacted_addresses_in_tx: dict[str:MongoImpactedAddress],
        amount: microCCD,
        sender: str,
        receiver: str,
    ):
        # first add to sander balance_movement
        if amount > 0:
            balance_movement = AccountStatementEntryType(
                transfer_out=[
                    AccountStatementTransferType(
                        amount=amount,
                        counterparty=receiver[:29] if len(receiver) > 20 else receiver,
                    )
                ]
            )
        else:
            balance_movement = None

        self.file_a_balance_movement(
            tx,
            impacted_addresses_in_tx,
            sender,
            balance_movement,
        )

        # then to the receiver balance_movement
        if amount > 0:
            balance_movement = AccountStatementEntryType(
                transfer_in=[
                    AccountStatementTransferType(
                        amount=amount,
                        counterparty=sender[:29] if len(sender) > 20 else sender,
                    )
                ]
            )
        else:
            balance_movement = None

        self.file_a_balance_movement(
            tx,
            impacted_addresses_in_tx,
            receiver,
            balance_movement,
        )

    def extract_impacted_addesses_from_tx(self, tx: CCD_BlockItemSummary):
        self.queues: dict[Collections, list]
        impacted_addresses_in_tx: dict[str:MongoImpactedAddress] = {}
        if tx.account_creation:
            balance_movement = AccountStatementEntryType()
            self.file_a_balance_movement(
                tx,
                impacted_addresses_in_tx,
                tx.account_creation.address,
                balance_movement,
            )
        if tx.account_transaction:
            # Always store the fee for the sender
            balance_movement = AccountStatementEntryType(
                transaction_fee=tx.account_transaction.cost
            )
            self.file_a_balance_movement(
                tx,
                impacted_addresses_in_tx,
                tx.account_transaction.sender,
                balance_movement,
            )

            # Next, for the below effect types, we need to store additional
            # balance movements.
            if tx.account_transaction.effects.contract_initialized:
                if tx.account_transaction.effects.contract_initialized.amount > 0:
                    self.file_balance_movements(
                        tx,
                        impacted_addresses_in_tx,
                        tx.account_transaction.effects.contract_initialized.amount,
                        tx.account_transaction.sender,
                        tx.account_transaction.effects.contract_initialized.address.to_str(),
                    )
                else:
                    balance_movement = None
                    self.file_a_balance_movement(
                        tx,
                        impacted_addresses_in_tx,
                        tx.account_transaction.effects.contract_initialized.address.to_str(),
                        balance_movement,
                    )
            if tx.account_transaction.effects.contract_update_issued:
                for (
                    effect
                ) in tx.account_transaction.effects.contract_update_issued.effects:
                    if effect.updated:
                        instigator_str = self.address_to_str(effect.updated.instigator)
                        self.file_balance_movements(
                            tx,
                            impacted_addresses_in_tx,
                            effect.updated.amount,
                            instigator_str,
                            effect.updated.address.to_str(),
                        )

                    elif effect.transferred:
                        self.file_balance_movements(
                            tx,
                            impacted_addresses_in_tx,
                            effect.transferred.amount,
                            effect.transferred.sender.to_str(),
                            effect.transferred.receiver,
                        )

                    elif effect.interrupted:
                        balance_movement = None
                        self.file_a_balance_movement(
                            tx,
                            impacted_addresses_in_tx,
                            effect.interrupted.address.to_str(),
                            balance_movement,
                        )

                    elif effect.resumed:
                        balance_movement = None
                        self.file_a_balance_movement(
                            tx,
                            impacted_addresses_in_tx,
                            effect.resumed.address.to_str(),
                            balance_movement,
                        )

            elif tx.account_transaction.effects.account_transfer:
                self.file_balance_movements(
                    tx,
                    impacted_addresses_in_tx,
                    tx.account_transaction.effects.account_transfer.amount,
                    tx.account_transaction.sender,
                    tx.account_transaction.effects.account_transfer.receiver,
                )

            elif tx.account_transaction.effects.transferred_with_schedule:
                self.file_balance_movements(
                    tx,
                    impacted_addresses_in_tx,
                    self.get_sum_amount_from_scheduled_transfer(
                        tx.account_transaction.effects.transferred_with_schedule.amount
                    ),
                    tx.account_transaction.sender,
                    tx.account_transaction.effects.transferred_with_schedule.receiver,
                )

            elif tx.account_transaction.effects.transferred_to_encrypted:
                balance_movement = AccountStatementEntryType(
                    amount_encrypted=tx.account_transaction.effects.transferred_to_encrypted.amount
                )
                self.file_a_balance_movement(
                    tx,
                    impacted_addresses_in_tx,
                    tx.account_transaction.sender,
                    balance_movement,
                )

            elif tx.account_transaction.effects.transferred_to_public:
                balance_movement = AccountStatementEntryType(
                    amount_decrypted=tx.account_transaction.effects.transferred_to_public.amount
                )
                self.file_a_balance_movement(
                    tx,
                    impacted_addresses_in_tx,
                    tx.account_transaction.sender,
                    balance_movement,
                )

        # now this tx is done, so add impacted_addresses to queue
        for ia in impacted_addresses_in_tx.values():
            ia: MongoImpactedAddress
            repl_dict = ia.model_dump(exclude_none=True)
            if "id" in repl_dict:
                del repl_dict["id"]

            self.queues[Queue.impacted_addresses].append(
                ReplaceOne(
                    {"_id": ia.id},
                    repl_dict,
                    upsert=True,
                )
            )

    ########### Impacted Addresses
