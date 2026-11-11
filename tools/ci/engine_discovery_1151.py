"""Read-only current-PE discovery, separate from frozen-byte reproduction.

No historical or current manifest is read. Exact RTTI name -> TypeDescriptor ->
COL self RVA/subobject -> vtable -> adjustor thunk independently locates parsers.
Own-name literal/atom roots feed a bounded token-dispatch interpreter. Optional
--callee reports aligned direct callers; --disassemble reads an explicit range.
The output is investigation evidence, not a runtime or permission attestation.

Install no project dependency. Supply a separately prepared capstone 5.0.7
vendor directory; its native library and version are checked before import.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import mmap
import struct
import sys
from importlib import import_module
from pathlib import Path

EXPECTED_DLL_SHA256 = "46b7c385efe50db4def8aa99aa351c44ea28b1f3c2ccbc4ca41dbb2a02340e39"

FIELDS = (
    "weight",
    "possible",
    "wanted_army_size",
    "recklessness",
    "max_progressiveness",
    "max_regressiveness",
    "change_law_chance",
    "wargoal_maneuvers_fraction",
    "obligation_value",
    "min_law_chance_to_pass",
    "revolution_aversion",
    "subject_value",
    "become_subject_value",
    "wanted_construction_output",
    "institution_scores",
    "wargoal_scores",
    "secret_goal_scores",
    "wanted_navy_size",
    "ship_construction_output_multiplier",
    "aggression",
    "nationalization_desire",
    "max_active_stances",
    "wanted_marines",
    "economic_vs_government_spending_balance",
    "target_marine_formation_size",
    "unacceptable_infamy_level",
    "undesirable_infamy_level",
    "diplomatic_play_neutrality",
    "diplomatic_play_boldness",
    "treaty_category_scores",
    "strategic_region_stance_type_scores",
    "wanted_num_supply_ships",
    "max_ship_design_complexity",
)
NAMES = (
    ".?AVCAIStrategy@@",
    ".?AVCBuildingType@@",
    ".?AVCCompanyType@@",
    ".?AVCTechnologyType@@",
    ".?AVCLawType@@",
    ".?AVCCountryLaw@@",
    ".?AVCCountryCreation@@",
    ".?AVCCountryFormation@@",
    ".?AVCAIStrategyDataBase@@",
    ".?AVCCountryCreationDatabase@@",
    ".?AVCCountryFormationDatabase@@",
    ".?AVCTreatyArticleType@@",
    ".?AV?$CJominiScriptScopeObject@VCCountry@@@@",
    ".?AV?$CJominiScriptScopeObject@VCState@@@@",
    ".?AV?$CJominiScriptScopeObject@VCStrategicRegion@@@@",
)


class PE:
    def __init__(self, executable):
        self.path = executable
        self.stream = executable.open("rb")
        self.raw = mmap.mmap(self.stream.fileno(), 0, access=mmap.ACCESS_READ)
        assert (
            hashlib.sha256(self.raw).hexdigest()
            == "fb4ec0698afd3d3b1a785926d57bd5d68c95a4afd04b56f6bd45abd7a5672b15"
        )
        h = struct.unpack_from("<I", self.raw, 0x3C)[0]
        n = struct.unpack_from("<H", self.raw, h + 6)[0]
        sz = struct.unpack_from("<H", self.raw, h + 20)[0]
        opt = h + 24
        self.base = struct.unpack_from("<Q", self.raw, opt + 24)[0]
        self.sections = []
        for i in range(n):
            o = opt + sz + 40 * i
            name = self.raw[o : o + 8].rstrip(b"\0").decode()
            _, rva, size, raw = struct.unpack_from("<IIII", self.raw, o + 8)
            self.sections.append((name, rva, raw, size))
        self.functions = []
        for name, _rva, off, size in self.sections:
            if name == ".pdata":
                self.functions = [
                    tuple(self.base + v for v in struct.unpack_from("<III", self.raw, o)[:2])
                    for o in range(off, off + size - 11, 12)
                    if struct.unpack_from("<I", self.raw, o)[0]
                ]
        self.starts = [a for a, b in self.functions]

    def va(self, o):
        for _, rva, off, sz in self.sections:
            if off <= o < off + sz:
                return self.base + rva + o - off
        return None

    def offset(self, a):
        for _, rva, off, sz in self.sections:
            if self.base + rva <= a < self.base + rva + sz:
                return off + a - self.base - rva
        raise ValueError(hex(a))

    def findall(self, value):
        o = 0
        while (o := self.raw.find(value, o)) >= 0:
            yield o
            o += 1

    def function(self, a):
        i = bisect.bisect_right(self.starts, a) - 1
        return (
            self.functions[i]
            if i >= 0 and self.functions[i][0] <= a < self.functions[i][1]
            else (a, a + 32)
        )

    def disasm(self, a, end=None):
        if end is None:
            a, end = self.function(a)
        capstone = import_module("capstone")

        decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        o = self.offset(a)
        return (
            "\n".join(
                f"  {i.address:016X}: {i.bytes.hex(' ').upper():<45} {i.mnemonic} {i.op_str}"
                for i in decoder.disasm(bytes(self.raw[o : o + end - a]), a)
            )
            + "\n"
        )

    def refs(self, target, kind="lea"):
        for prefix in (b"\x48\x8d", b"\x4c\x8d") if kind == "lea" else (b"\xe8",):
            for o in self.findall(prefix):
                a = self.va(o)
                if a is None:
                    continue
                if kind == "lea":
                    if self.raw[o + 2] & 0xC7 != 5:
                        continue
                    dst = a + 7 + struct.unpack_from("<i", self.raw, o + 3)[0]
                else:
                    dst = a + 5 + struct.unpack_from("<i", self.raw, o + 1)[0]
                if dst == target:
                    yield a, self.function(a)

    def rtti(self, name):
        found = []
        for o in self.findall(name.encode() + b"\0"):
            td = self.va(o) - 16
            for p in self.findall(struct.pack("<I", td - self.base)):
                col = self.va(p) - 12
                if col is None:
                    continue
                raw = self.raw[p - 12 : p + 12]
                if len(raw) != 24:
                    continue
                sig, sub, _cd, _tdr, _cl, own = struct.unpack("<6I", raw)
                if sig != 1 or own != col - self.base:
                    continue
                tables = [self.va(q) + 8 for q in self.findall(struct.pack("<Q", col))]
                found.append(
                    {
                        "name": name,
                        "type_descriptor": hex(td),
                        "col": hex(col),
                        "subobject": hex(sub),
                        "vtables": [hex(a) for a in tables],
                    }
                )
        return found

    def atom(self, name):
        results = []
        for o in self.findall(name.encode() + b"\0"):
            if self.raw[o - 1] != 0:
                continue
            lit = self.va(o)
            for p in self.findall(struct.pack("<Q", lit)):
                a = self.va(p) - 8
                token = struct.unpack_from("<I", self.raw, p - 8)[0]
                if token < 100000 and self.raw[p - 4 : p] == b"\0" * 4:
                    results.append({"literal": hex(lit), "atom": hex(a), "token": hex(token)})
        return results

    def point(self, label, a, n):
        o = self.offset(a)
        return {
            "label": label,
            "va": hex(a),
            "rva": hex(a - self.base),
            "file_offset": hex(o),
            "bytes": self.raw[o : o + n].hex(),
        }


def trace(p, cs, constants, start, token):
    regs = {"r8d": token, "r8": token}
    cmp = None
    a = start
    path = []
    selected = None

    def put(name, value):
        regs[name] = value
        aliases = {"eax": "rax", "ebx": "rbx", "ecx": "rcx", "edx": "rdx", "r8d": "r8"}
        if name in aliases:
            regs[aliases[name]] = value & 0xFFFFFFFF

    def get(op):
        if op.type == constants.X86_OP_IMM:
            return op.imm
        if op.type == constants.X86_OP_REG:
            return regs.get(cs.reg_name(op.reg))
        if op.type == constants.X86_OP_MEM:
            base = (
                a + i.size
                if op.mem.base == constants.X86_REG_RIP
                else regs.get(cs.reg_name(op.mem.base), 0 if not op.mem.base else None)
            )
            index = regs.get(cs.reg_name(op.mem.index), 0 if not op.mem.index else None)
            if base is None or index is None:
                return None
            address = base + index * op.mem.scale + op.mem.disp
            if 0x140000000 <= address < 0x146100000:
                return int.from_bytes(
                    p.raw[p.offset(address) : p.offset(address) + op.size], "little"
                )
        return None

    for _ in range(120):
        o = p.offset(a)
        i = next(cs.disasm(bytes(p.raw[o : o + 15]), a))
        ops = i.operands
        path.append({"va": hex(a), "instruction": i.mnemonic + " " + i.op_str})
        if (
            i.mnemonic in {"cmp", "sub", "add"}
            and ops[0].type == constants.X86_OP_REG
            and (v := get(ops[0])) is not None
            and (w := get(ops[1])) is not None
        ):
            cmp = (v, w)
            if i.mnemonic != "cmp":
                value = (v - w if i.mnemonic == "sub" else v + w) & ((1 << (ops[0].size * 8)) - 1)
                put(cs.reg_name(ops[0].reg), value)
        elif i.mnemonic.startswith("j"):
            if i.mnemonic == "jmp":
                take = True
            elif cmp is None:
                break
            else:
                v, w = cmp

                def signed(n):
                    return n if n < 0x80000000 else n - 0x100000000

                take = {
                    "je": v == w,
                    "jne": v != w,
                    "jg": signed(v) > signed(w),
                    "jge": signed(v) >= signed(w),
                    "jl": signed(v) < signed(w),
                    "jle": signed(v) <= signed(w),
                    "ja": v > w,
                    "jae": v >= w,
                    "jb": v < w,
                    "jbe": v <= w,
                }.get(i.mnemonic)
                if take is None:
                    break
            if take:
                target = get(ops[0])
                if target is None:
                    break
                selected = target
                a = target
                continue
        elif (
            i.mnemonic in {"mov", "movzx", "movsxd", "lea"} and ops[0].type == constants.X86_OP_REG
        ):
            if i.mnemonic == "lea":
                mem = ops[1].mem
                base = (
                    a + i.size
                    if mem.base == constants.X86_REG_RIP
                    else regs.get(cs.reg_name(mem.base), 0 if not mem.base else None)
                )
                index = regs.get(cs.reg_name(mem.index), 0 if not mem.index else None)
                v = None if base is None or index is None else base + index * mem.scale + mem.disp
            else:
                v = get(ops[1])
            if v is not None:
                put(cs.reg_name(ops[0].reg), v)
            elif selected is not None:
                break
        elif i.mnemonic in {"call", "ret"} or (
            selected is not None and i.mnemonic not in {"push", "nop"}
        ):
            break
        a += i.size
    return {"branch": hex(selected) if selected else None, "path": path}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--vendor", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--callee", action="append", default=[], type=lambda value: int(value, 0))
    parser.add_argument(
        "--disassemble", nargs=2, action="append", default=[], metavar=("START", "END")
    )
    args = parser.parse_args()
    vendor = args.vendor.resolve()
    dll = vendor / "capstone/lib/capstone.dll"
    if hashlib.sha256(dll.read_bytes()).hexdigest() != EXPECTED_DLL_SHA256:
        parser.error("Unexpected capstone native-library identity")
    sys.path.insert(0, str(vendor))
    capstone = import_module("capstone")
    constants = import_module("capstone.x86_const")

    if capstone.__version__ != "5.0.7" or not Path(capstone.__file__).resolve().is_relative_to(
        vendor
    ):
        parser.error("Expected explicit capstone 5.0.7 vendor")
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if not output.is_relative_to(root / "tools/out"):
        parser.error("Investigation output must stay in tools/out")
    output.mkdir(parents=True, exist_ok=True)
    p = PE(args.exe.resolve())
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    cs.detail = True
    result = {
        "schema": 1,
        "evidence_category": "static_check",
        "runtime": "unknown",
        "exe_sha256": hashlib.sha256(p.raw).hexdigest(),
        "exe_bytes": len(p.raw),
        "capstone_version": capstone.__version__,
        "capstone_dll_sha256": EXPECTED_DLL_SHA256,
        "rtti": {},
        "atoms": {},
        "token_paths": {},
        "callers": {},
    }
    for name in NAMES:
        rows = p.rtti(name)
        for row in rows:
            row["slots"] = {}
            for vtable in row["vtables"]:
                pointers = struct.unpack_from("<6Q", p.raw, p.offset(int(vtable, 16)))
                row["slots"][vtable] = [hex(pointer) for pointer in pointers]
                # The parse interface owns slot4. Adjacent COL/vtable data
                # cannot be treated as further methods of this interface.
                for slot, pointer in enumerate(pointers):
                    if slot != 4 or row["subobject"] == "0x0":
                        continue
                    try:
                        off = p.offset(pointer)
                    except ValueError:
                        continue
                    if p.raw[off : off + 8] == bytes.fromhex("486341fc482bc8e9"):
                        row["parser"] = hex(
                            pointer + 12 + struct.unpack_from("<i", p.raw, off + 8)[0]
                        )
                        row["parser_thunk"] = hex(pointer)
        result["rtti"][name] = rows
    strategies = result["rtti"][".?AVCAIStrategy@@"]
    (strategy,) = [row for row in strategies if row["subobject"] == "0x20d8" and "parser" in row]
    start = int(strategy["parser"], 16)
    for name in FIELDS:
        atoms = p.atom(name)
        (atom,) = atoms
        result["atoms"][name] = atom
        result["token_paths"][name] = trace(p, cs, constants, start, int(atom["token"], 16))
    for callee in args.callee:
        calls = []
        for a, (begin, end) in p.refs(callee, "call"):
            if begin == a and end == a + 32:
                continue
            instructions = list(
                cs.disasm(bytes(p.raw[p.offset(begin) : p.offset(begin) + end - begin]), begin)
            )
            if any(
                i.address == a
                and i.mnemonic == "call"
                and i.operands[0].type == constants.X86_OP_IMM
                and i.operands[0].imm == callee
                for i in instructions
            ):
                calls.append({"call": hex(a), "unwind_begin": hex(begin), "unwind_end": hex(end)})
        result["callers"][hex(callee)] = calls
    for begin, end in args.disassemble:
        a, b = int(begin, 0), int(end, 0)
        (output / f"disassembly-{a:x}-{b:x}.txt").write_text(
            p.disasm(a, b), encoding="utf8", newline="\n"
        )
    (output / "current-discovery.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf8", newline="\n"
    )
    print(
        f"Current independent discovery: {len(result['rtti'])} RTTI types, {len(result['token_paths'])} field tokens, {sum(len(v) for v in result['callers'].values())} aligned calls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
