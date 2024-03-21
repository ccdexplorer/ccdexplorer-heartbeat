import pytest
import datetime as dt
from rich import print
from heartbeat import Heartbeat
from pymongo import ASCENDING
from env import *
from ccdexplorer_fundamentals.mongodb import (
    MongoDB,
    MongoMotor,
    Collections,
)
from ccdexplorer_fundamentals.tooter import Tooter
from ccdexplorer_fundamentals.GRPCClient import GRPCClient
from rich import print
from ccdexplorer_fundamentals.cis import (
    MongoTypeTokenAddress,
    TokenMetaData,
    MongoTypeLoggedEvent,
    MongoTypeTokenHolderAddress,
    MongoTypeTokenLink,
    FailedAttempt,
    MongoTypeTokenForAddress,
    mintEvent,
    transferEvent,
    burnEvent,
    tokenMetadataEvent,
    MongoTypeTokensTag,
)


def get_logged_events_for_token_address(token_address: str, mongodb: MongoDB):
    events_for_token_address = [
        MongoTypeLoggedEvent(**x)
        for x in mongodb.mainnet[Collections.tokens_logged_events]
        .find({"token_address": token_address})
        .sort(
            [
                ("block_height", ASCENDING),
                ("tx_index", ASCENDING),
                ("ordering", ASCENDING),
            ]
        )
    ]
    return events_for_token_address


def filter_for_address(
    address_to_follow: str, events_for_token_address: list[MongoTypeLoggedEvent]
):
    filtered_list = []
    for event in events_for_token_address:
        if event.result:
            if event.result.get("from_address") == address_to_follow:
                filtered_list.append(event)
                continue
            if event.result.get("to_address") == address_to_follow:
                filtered_list.append(event)
                continue

    return filtered_list


def create_new_token_address(token_address: str) -> MongoTypeTokenAddress:
    instance_address = token_address.split("-")[0]
    token_id = token_address.split("-")[1]
    token_address = MongoTypeTokenAddress(
        **{
            "_id": token_address,
            "contract": instance_address,
            "token_id": token_id,
            "token_amount": str(int(0)),  # mongo limitation on int size
            # not that we need to include the token_holders here, because we use it in code (but do not store it!)
            "token_holders": {},  # {CCD_AccountAddress, str(token_amount)}
            "last_height_processed": -1,
            "hidden": False,
        }
    )
    return token_address


@pytest.fixture
def grpcclient():
    return GRPCClient()


# @pytest.fixture
# def mongodb():

#     return mongodb


@pytest.fixture
def heartbeat():
    grpcclient = GRPCClient()
    tooter = Tooter()

    mongodb = MongoDB(tooter)
    motormongo = MongoMotor(tooter)
    heartbeat = Heartbeat(grpcclient, None, mongodb, motormongo, "mainnet")
    heartbeat.address_to_follow = None
    return heartbeat


def test_logs(heartbeat: Heartbeat):  # grpcclient: GRPCClient, mongodb: MongoDB):
    address_to_follow = "4JafBcWeHt5K92EXyStUdzii5Jt32BSDiZ2EMAYcnYBtrAAePA"
    token_address = "<9338,0>-"
    token_address_as_class = create_new_token_address(token_address)
    events_for_token_address = get_logged_events_for_token_address(
        token_address, heartbeat.mongodb
    )
    filtered_events = filter_for_address(address_to_follow, events_for_token_address)

    token_address_as_class = heartbeat.execute_logged_event(
        token_address_as_class,
        filtered_events[0],
    )
    assert (
        token_address_as_class.token_holders.get(address_to_follow)
        == filtered_events[0].result["token_amount"]
    )

    token_address_as_class = heartbeat.execute_logged_event(
        token_address_as_class,
        filtered_events[1],
    )
    assert token_address_as_class.token_holders.get(address_to_follow) == str(
        int(filtered_events[0].result["token_amount"])
        + int(filtered_events[1].result["token_amount"])
    )

    token_address_as_class = heartbeat.execute_logged_event(
        token_address_as_class,
        filtered_events[2],
    )
    assert token_address_as_class.token_holders.get(address_to_follow) == str(
        int(filtered_events[0].result["token_amount"])
        + int(filtered_events[1].result["token_amount"])
        + int(filtered_events[2].result["token_amount"])
    )

    token_address_as_class = heartbeat.execute_logged_event(
        token_address_as_class,
        filtered_events[3],
    )
    assert token_address_as_class.token_holders.get(address_to_follow) == str(
        int(filtered_events[0].result["token_amount"])
        + int(filtered_events[1].result["token_amount"])
        + int(filtered_events[2].result["token_amount"])
        + int(filtered_events[3].result["token_amount"])
    )

    token_address_as_class = heartbeat.execute_logged_event(
        token_address_as_class,
        filtered_events[4],
    )
    assert token_address_as_class.token_holders.get(address_to_follow) == str(
        int(filtered_events[0].result["token_amount"])
        + int(filtered_events[1].result["token_amount"])
        + int(filtered_events[2].result["token_amount"])
        + int(filtered_events[3].result["token_amount"])
        - int(filtered_events[4].result["token_amount"])
    )
    print(token_address_as_class)
    # print(filtered_events)
