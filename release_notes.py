from ccdexplorer_fundamentals.mongodb import (
    MongoDB,
    MongoMotor,
    Collections,
    CollectionsUtilities,
)
from ccdexplorer_fundamentals.GRPCClient import GRPCClient
from ccdexplorer_fundamentals.tooter import Tooter, TooterChannel, TooterType
from pymongo import ASCENDING, DESCENDING, ReplaceOne, DeleteOne
from ccdexplorer_fundamentals.GRPCClient.CCD_Types import *
from ccdexplorer_fundamentals.cis import MongoTypeTokenAddress
import datetime as dt
from env import *
from pydantic import BaseModel
import json
from rich import print
from typing import Optional

grpcclient = GRPCClient()
tooter = Tooter()

mongodb = MongoDB(tooter)
motormongo = MongoMotor(tooter)


class ReleaseNote(BaseModel):
    identifier: str
    date: dt.date
    new: Optional[list[str]] = None
    updated: Optional[list[str]] = None
    fixed: Optional[list[str]] = None
    removed: Optional[list[str]] = None


net = "mainnet"
db_to_use = mongodb.testnet if net == "testnet" else mongodb.mainnet


release_note = ReleaseNote(identifier="2024.5", date=dt.date(2024, 2, 21))
release_note.new = ["""Added MOTODEX to the CIS-2 Tokens verified list.  """]
# release_note.updated = [
#     "(Site): Updated links to accounts to include the index instead of the address and updated the visible title of the link to also be the index if it's not a globally or user labeled account. Users are more able to recognize account indices (5 numbers) than 50 char account addresses, who knew?",
#     "(Bot): For validated smart contracts, the name is now displayed when a method is called on the contract and visible in the corresponding notification. ",
# ]


# release_note.fixed = []
# release_note.removed = ["Removed Wallet Proxy account lookup."]


d: dict = json.loads(release_note.model_dump_json(exclude_none=True))
d["_id"] = d["identifier"]
del d["identifier"]

rn = [
    ReplaceOne(
        {"_id": release_note.identifier},
        replacement=d,
        upsert=True,
    )
]

tooter.relay(
    channel=TooterChannel.NOTIFIER,
    title="",
    chat_id=ADMIN_CHAT_ID,
    body=f"Added release note {release_note.identifier}: {d}",
    notifier_type=TooterType.INFO,
)
_ = mongodb.utilities[CollectionsUtilities.release_notes].bulk_write(rn)
