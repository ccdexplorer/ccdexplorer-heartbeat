# CCDExplorer Heartbeat

This repo is the `heartbeat` for CCDExplorer.io.
It stores all blocks, transactions and indices and more in the corresponding MongoDB collections. Many other services (notably the site and the notification bot) depend on the `heartbeat`.

All methods below get called on a schedule, are designed to work independently and write their results to a set of MongoDB collections. Note that all documents we write to collections have predictable `_ids`, which makes it easy to redo (parts of) a process.

Methods:
1. [Get Finalized Blocks](#method-get-finalized-blocks)
2. [Process Blocks](#method-process-blocks)
3. [Send to Mongo](#send-to-mongo)
4. [Get Special Purpose Blocks](#method-get-special-purpose-blocks)
5. [Process Special Purpose Blocks](#method-process-special-purpose-blocks)
6. [Update Token Accounting](#method-token-accounting)
7. [Get Redo Token Addresses](#method-get-redo-token-addresses)
8. [Special Purpose Token Accounting](#method-special-purpose-token-accounting)
9. [Update Nodes from Dashboard](#method-update-nodes)
10. [Update Exchange Rates for Tokens](#method-update-exchange-rates)




## Method: Get Finalized Blocks

This methods runs forever, with a sleep of 1 sec. The goal is to get **finalized blocks** that have not yet been processed and adding them to an internal queue `finalized_block_infos_to_process`.
It performs this task by by calling `get_finalized_block_at_height` on `grpcclient` from the chosen `net`.

The method batches blocks to be processed up to `MAX_BLOCKS_PER_RUN`. Hence, if this process is stopped and restarted at a later stage, only `MAX_BLOCKS_PER_RUN` are fetched and added to the queue. Without this limit, the process could easily run out of memory if for example, it hasn't run for a day, and it needs to catch up 40K+ blocks. 

### Logic
1. Every second we start with a request counter of 0. This counter is compared to `MAX_BLOCKS_PER_RUN` to determine if we have reached the batch size.
2. Next, we retrieve the current stored value in the `helpers` collection for `_id`: `heartbeat_last_processed_block`.
3. Entering the while loop if we think we need to look for new finalized blocks.
4. We increment `heartbeat_last_processed_block_height` with 1 to get the next finalized block. 
5. Check if this new height isn't already in the queue `finalized_block_infos_to_process` to be processed, which can occur if we search for blocks too quickly, while processing hasn't finished yet. 
6. We then retrieve the finalized block at the height `heartbeat_last_processed_block_height`. If such a block exists, it is appended to the queue. 

## Method: Process Blocks
This methods runs forever, with a sleep of 1 sec. The goal is to take the queue `finalized_block_infos_to_process` and send this queue to `process_list_of_blocks`.

When this call returns, the method `log_last_processed_message_in_mongo` gets called to store the helper document `heartbeat_last_processed_block` to update the last block we have processed.

## Method: Process List of Blocks
This method takes as input a list of blocks that need processing. 

This method is the workhorse of **Heartbeat**, kicking of the various processes to process a block. The method is used for the regular finalized blocks, as well as special purpose blocks. This is controlled by calling the method with `special_purpose=True`. Typically the blocks to be processed are added through the regular `get_finalized_blocks` method. 

However, there may be a need to re-process a block out of sync. To enable this, we can add a list of blocks to a specified document in the `helpers` collection. This document regularly gets read, and if found, these blocks are added to the `special_purpose_block_infos_to_process` queue, which gets processed on a schedule calling the same `process_list_of_blocks`, however with `special_purpose=True`. This is needed as also token accounting is performed and if we re-process a block out of sync, we also need to redo token accounting for any  accounts and/or tokens found in the transactions.



TODO: `existing_source_modules`

Steps every block on the queue:

#### Add Block and Txs to Queue
This method takes a block and retrieves its transactions (if any) and updates the block with `transaction_hashes`.
The updated block is sent to the `MongoDB queue.Blocks`.

For each block with transactions, we call `generate_indices_based_on_transactions`.

##### generate_indices_based_on_transactions
This method takes as input a list of transactions from a block, and applies rules to determine whether specific indexes need to be stored for these transactions, but also stored CIS-2 logged events. These logged events are processed in a separate process. This is discussed in detail in [Token Accounting](#token-accounting).

To get to this result, we call `classify_transaction` for the transaction. This classifies the transaction and returns a `ClassificationResult` object, containing `sender`, `receiver`, `tx_hash`, `memo`, `amount`, `type`, `contents`, `accounts_involved_all`, `accounts_involved_transfer`, `contracts_involved`, `list_of_contracts_involved`.

We use this return object to update our collections. 

* `Mongo queue.involved_all` is used for all transactions
* `Mongo queue.involved_transfer` is used for all transactions
* `Mongo queue.involved_contract` is used for all transactions that involve a smart contract. Note that, as transactions with smart contract often involve many calls do various instances, a transaction will be stored for each individual smart contract.
* `Mongo queue.instances` is used to upsert information about the instance.
* `Mongo queue.modules` is used to upsert information about the module.

#### Lookout for Payday
This method looks at a block and determines if the special events make it a payday block. If so, we will store in the `helpers` collection a document with `_id`: `last_known_payday`, that contains details about the payday block we have just encountered. Note that this helper document is used by the `payday-MAINNET` repo. This repo checks periodically the last payday as stored in collection `paydays`. If the helper document is newer, the payday process is started there. 
If we are processing multiple days worth of blocks here, we might end up overwriting the helper document with new payday information before the payday repo has had a chance to process it. Therefore the bool `payday_not_yet_processed` is introduced to prevent this.

#### Lookout for End of Day
This method looks at a block and determines if it's the last block of the day. If found, it prepares a dictionary with day information (height, slot time, hash, for first and last block of the day) and stores this in `Mongo queue.block_per_day`.

# Send To Mongo
The purpose of this method is to take all `Mongo queues` and send them to their respective collections. 

* `queue.blocks` to `Collection.blocks`
* `queue.transactions` to `Collection.transactions`
* `queue.involved_all` to `Collection.involved_accounts_all`
* `queue.involved_all` to `Collection.involved_accounts_all`
* `queue.involved_transfer` to `Collection.involved_accounts_transfer`
* `queue.involved_contract` to `Collection.involved_contracts`
* `queue.instances` to `Collection.instances`
* `queue.modules` to `Collection.modules`
* `queue.block_per_day` to `Collection.blocks_per_day`
* `queue.logged_events` to `Collection.tokens_logged_events`
* `queue.token_addresses_to_redo_accounting` to helper document `redo_token_addresses`
* `queue.provenance_contracts_to_add` to `Collection.tokens_tags` for specific Provenance token tag. This is used only if there is a new Provenance contract detected. 

Note that all queues are sent async, and hence can appear to be out of order in the console.

## Method: Get Special Purpose Blocks

There may be a need to re-process a block out of sync. To enable this, we can add a list of blocks to a specified document in the `helpers` collection. This document regularly gets read in this method, and if found, these blocks are added to the `special_purpose_block_infos_to_process` queue, which gets processed on a schedule calling the same `process_list_of_blocks`, however with `special_purpose=True`. Once the helper is retrieved, it is set to an empty list again to prevent redoing the same set of blocks again. 

We need to set the `special_purpose` flag, as we may redo a block that has transctions with logged events that lead to changes in token accounting. Therefore, if we re-process a block out of sync, we also need to redo token accounting for any accounts and/or tokens found in the transactions.

## Method: Process Special PurposeBlocks
This methods runs forever, with a sleep of 5 sec. The goal is to take the queue `special_purpose_block_infos_to_process` and send this queue to `process_list_of_blocks`, with `special_purpose=True`.

## Method: Token Accounting

Token accounting is the process of accounting for mints, burns and transfers for CIS-2 tokens. These tokens are not stored on-chain. Instead, account holdings can only be deduced from the `logged events`. Therefore it is very important that logged events are stored correctly, with no omissions and duplications. Also, the order in which logged events are applied, matters, as you can't burn or transfer tokens you do not own. 

Check [CIS-2 Specification for logged events](http://proposals.concordium.software/CIS/cis-2.html#logged-events).

### Relevant Collections
Below are example documents as they are stored in the respective collections. 

#### tokens_logged_events
This collection stores logged events.
``` py
{
  "_id": "5351380-<8586,0>-45000000-fe0445000000010043a0c163c7f7a8e58ba325fde7b504153592ded8507f75264fb4fc4b30000002-updated-23-0-0",
  "logged_event": "fe0445000000010043a0c163c7f7a8e58ba325fde7b504153592ded8507f75264fb4fc4b30000002",
  "result": {
    "tag": 254,
    "token_id": "45000000",
    "token_amount": "1",
    "to_address": "3TXeDWoBvHQpn7uisvRP8miX47WF4tpkKBidM4MLsDPeshUTs8"
  },
  "tag": 254,
  "event_type": "mint_event",
  "block_height": 5351380,
  "tx_hash": "2c0a2e67766c41c8d4c2484db5a9804f937ab862f8528639522d2cb1bb152e18",
  "tx_index": 23,
  "ordering": 1,
  "token_address": "<8586,0>-45000000",
  "contract": "<8586,0>"
}
```

#### tokens_token_addresses
This collection stores individual tokens.
``` py
{
  "_id": "<9403,0>-01288764e78695027bd972e9b654cde28df2563e56b3ed66a4c8f4dcb3c08cec",
  "contract": "<9403,0>",
  "token_id": "01288764e78695027bd972e9b654cde28df2563e56b3ed66a4c8f4dcb3c08cec",
  "token_amount": "1",
  "metadata_url": "https://nft.ptags.io/01288764E78695027BD972E9B654CDE28DF2563E56B3ED66A4C8F4DCB3C08CEC",
  "last_height_processed": 14189078,
  "token_metadata": {
    "name": "Psi 2009",
    "unique": true,
    "description": "Psi 2009",
    "thumbnail": {
      "url": "https://storage.googleapis.com/provenance_images/82_4ce5e65e-23a3-47fe-bc5e-109856fa700d.png"
    },
    "display": {
      "url": "https://storage.googleapis.com/provenance_images/82_4ce5e65e-23a3-47fe-bc5e-109856fa700d.png"
    },
    "attributes": [
      {
        "type": "string",
        "name": "nfc_id",
        "value": "01288764E78695027BD972E9B654CDE28DF2563E56B3ED66A4C8F4DCB3C08CEC"
      }
    ]
  },
  "hidden": false
}
```

#### tokens_links
This collections stores links between accounts and tokens.
``` py
{
  "_id": "<8586,0>-50000000-3TXeDWoBvHQpn7uisvRP8miX47WF4tpkKBidM4MLsDPgXn9Rgv",
  "account_address": "3TXeDWoBvHQpn7uisvRP8miX47WF4tpkKBidM4MLsDPgXn9Rgv",
  "account_address_canonical": "3TXeDWoBvHQpn7uisvRP8miX47WF4",
  "token_holding": {
    "token_address": "<8586,0>-50000000",
    "contract": "<8586,0>",
    "token_id": "50000000",
    "token_amount": "1"
  }
}
```

#### tokens_tags
This collection stores recognized tokens/contracts and summarizes this into tags.
``` py
{
  "_id": "USDT",
  "contracts": [
    "<9341,0>"
  ],
  "tag_template": false,
  "single_use_contract": true,
  "logo_url": "https://cryptologos.cc/logos/tether-usdt-logo.svg?v=025",
  "decimals": {
    "$numberLong": "6"
  },
  "owner": "Arabella",
  "module_name": "cis2-bridgeable"
}
```

The starting point is reading the helper document `token_accounting_last_processed_block`. This value indicates the last block that was processed for logged events. Hence, if we start at logged events after this block, there is no double counting. If this value is either not present or set to -1, all token_addresses (and associated token_accounts) will be reset. 

**Need to redo token accounting?**: Set helper document `token_accounting_last_processed_block` to -1. 


We collect all logged events from the collection `tokens_logged_events` with the following query:

``` py
{"block_height": {"$gt": token_accounting_last_processed_block}}
.sort(
    [
        ("block_height", ASCENDING),
        ("tx_index", ASCENDING),
        ("ordering", ASCENDING),
    ]
).limit(1000)
```

If there are `logged_events` to process, we sort the events into a dict `events_by_token_address`, keyed on token_address and contains an ordered list of logged events related to this token_address.

Next, we retrieve the token_addresses from the collection for all token addresses that are mentioned in the logged events. 
Finally, we retrieve all token_links from the collection for all token addresses that are mentioned in the logged events. 
``` py                    
events_by_token_address: dict[str, list] = {}
for log in result:
    events_by_token_address[log.token_address] = (
        events_by_token_address.get(log.token_address, [])
    )
    events_by_token_address[log.token_address].append(log)
```


We then loop through all `token_addresses` that have logged events to process and call `token_accounting_for_token_address`. 

The method `token_accounting_for_token_address` first deterines the need to create a new token address (when we are starting over with token accounting, setting `token_accounting_last_processed_block` to -1, or if the `token_address` doesn't exist).

Then for this `token_address`, we loop through all logged events that need processing, and call `execute_logged_event`. 

This method preforms the neccesary actions on the `token_address_as_class` variable. Once all logged events for a `token_address` are executed, we save the result back to the collection `tokens_token_addresses`. 

Note that token holder information is stored in the `tokens_links` collection.

Finally, after all logged events are processed for all token addresses, write back to the helper collection for `_id`: `token_accounting_last_processed_block` the block_height of the last logged event. 