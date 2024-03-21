# ruff: noqa: F403, F405, E402, E501, E722
from .utils import Utils, Queue
from ccdexplorer_fundamentals.GRPCClient.CCD_Types import *
from ccdexplorer_fundamentals.enums import NET
from ccdexplorer_fundamentals.GRPCClient import GRPCClient
from ccdexplorer_fundamentals.mongodb import Collections
from pymongo import ReplaceOne
from env import *
import ccdexplorer_fundamentals.GRPCClient.wadze as wadze
import io
from rich.console import Console

console = Console()


class ModuleLogic(Utils):
    def get_module_metadata(self, block_hash: str, module_ref: str) -> dict[str, str]:
        self.grpcclient: GRPCClient
        ms = self.grpcclient.get_module_source(module_ref, block_hash, NET(self.net))

        if ms.v0:
            bs = io.BytesIO(bytes.fromhex(ms.v0))
        else:
            bs = io.BytesIO(bytes.fromhex(ms.v1))

        module = wadze.parse_module(bs.read())

        results = {}

        if "export" in module.keys():
            for line in module["export"]:
                split_line = str(line).split("(")
                if split_line[0] == "ExportFunction":
                    split_line = str(line).split("'")
                    name = split_line[1]

                    if name[:5] == "init_":
                        results["module_name"] = name[5:]
                    else:
                        method_name = name.split(".")[1] if "." in name else name
                        if "methods" in results:
                            results["methods"].append(method_name)
                        else:
                            results["methods"] = [method_name]

        return results

    def add_back_updated_modules_to_queue(
        self, current_block_to_process: CCD_BlockInfo
    ):
        self.queues: dict[Collections, list]
        self.queues[Queue.modules] = []

        # make this into a set to remove duplicates...remember testnet with 991K module updates in 1K blocks...
        self.queues[Queue.updated_modules] = list(
            set(self.queues[Queue.updated_modules])
        )
        # for module_ref in self.existing_source_modules.keys():
        for module_ref in self.queues[Queue.updated_modules]:
            self.get_module_data_and_add_to_queue(module_ref)

    def get_module_data_and_add_to_queue(self, module_ref: CCD_ModuleRef):
        self.existing_source_modules: dict[CCD_ModuleRef, set]
        try:
            results = self.get_module_metadata("last_final", module_ref)
        except:
            results = {"module_name": "", "methods": []}
        module = {
            "_id": module_ref,
            "module_name": (
                results["module_name"] if "module_name" in results.keys() else None
            ),
            "methods": results["methods"] if "methods" in results.keys() else None,
            "contracts": (
                list(self.existing_source_modules.get(module_ref, []))
                if self.existing_source_modules.get(module_ref)
                else None
            ),
        }
        self.queues[Queue.modules].append(
            ReplaceOne({"_id": module_ref}, module, upsert=True)
        )
