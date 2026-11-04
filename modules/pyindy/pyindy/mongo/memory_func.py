#!/usr/bin/env python
# coding: utf-8 -*-

"""Miscellaneous Functions used in the Memorization/Forgetting processes"""

import math
from typing import Any, Dict, List, Literal

from pymongo.collection import Collection

ValidIndex = Literal[1, -1, "2d", "text"]


class MemoryFunction:
    """Uninstantiable class with functions used in the memorization/forgetting process.
    Memory Modules inherit this class."""

    def memory_list_add(
        self, memory_list: list, new_memory: Any, maxcap=7
    ) -> List:
        """Adds a new Memory to a list of Memories, given a hard cap of `maxcap`.
        If the cap is exceeded, the oldest memory is removed from the list."""
        memory_list = memory_list[:]  # Soft copy
        while len(memory_list) >= maxcap:
            memory_list = memory_list[1:]
        memory_list.append(new_memory)
        return memory_list

    def memory_list_merge(
        self, old_mem_list: list, new_mem_list: list, maxcap=7
    ) -> List:
        """Merges two lists of memories into a new one, given a hard cap of `maxcap`.
        If the cap is exceeded, the oldest memories are removed from the list.
        """
        memory_list = old_mem_list + new_mem_list
        if len(memory_list) > maxcap:
            deficit = len(memory_list) - maxcap
            memory_list = memory_list[:1] + memory_list[deficit + 1 :]
        return memory_list

    def memory_dict_add(
        self, memory_dict: dict, new_memory: Any, new_memory_key: Any, maxcap=7
    ) -> Dict:
        """Adds a new Memory to a dictionary of Memories, given a hard cap of `maxcap`.
        If cap is exceeded, oldest memory is removed
        """
        memory_dict = dict(memory_dict.items())
        memory_dict[str(new_memory_key)] = new_memory
        keys_sorted = sorted(memory_dict.keys(), reverse=True)
        keys_removed = set()
        while len(keys_sorted) > maxcap:
            keys_removed = keys_sorted.pop()
        for k in keys_removed:
            del memory_dict[k]
        return memory_dict

    def f_logistic(self, x: float, x0: float, logv: float, k: float) -> float:
        """Logistic Function"""
        return logv / (1 + math.exp(-k * (x - x0)))

    def get_forgetcurve(
        self, mu: float, a: float, t: float, d: float
    ) -> float:
        """Forgetting Curve (Weibull-based)"""
        return mu * math.exp(-math.pow((a * t) / d, d))

    def estimate_forgetting_t(
        self, mu: float, a: float, t: float, d: float, fline: float
    ) -> float:
        """Create future timestamp for estimated forgetting time"""
        # If the curve is entirely below fline...
        if mu <= fline:
            # It must be schedule to forget NOW (or ASAP)
            # (otherwise estimation would be an imaginary domain)
            return t

        try:
            tdelta = (d / a) * math.pow(-math.log(fline / mu), 1 / d)
        except OverflowError as exc:
            raise OverflowError(
                f"For params: {mu}, {a}, {t}, {d}, {fline}"
            ) from exc
        except ValueError as exc:
            # Usually a Domain error.
            raise ValueError(
                f"For params: {mu}, {a}, {t}, {d}, {fline}"
            ) from exc

        return t + tdelta

    def update_forget_time(self, stm_obj: dict, tstamp) -> None:
        stm_obj["forgetting_curve"]["forget_time"] = (
            self.estimate_forgetting_t(
                mu=stm_obj["forgetting_curve"]["mu"],
                a=stm_obj["forgetting_curve"]["a"],
                d=stm_obj["forgetting_curve"]["d"],
                fline=stm_obj["forgetting_curve"]["f_line"],
                t=tstamp,
            )
        )

    def setup_index(
        self,
        coll: Collection,
        fieldname: str,
        indextype: ValidIndex,
        dropifexists=False,
    ):
        indices = dict(coll.index_information())
        index_name = f"{fieldname}_{indextype}"

        if index_name in indices:
            if dropifexists:
                coll.drop_index(index_name)
            else:
                return
        coll.create_index([(fieldname, indextype)])
