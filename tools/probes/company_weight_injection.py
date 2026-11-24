"""Verify the frozen D08 company candidate and optionally recompile its score in memory."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from pdx import decision_adapters, distribution, native_authority_capture
from pdx.situated import compiler, engine_scope, r2_reader_authority
from pdx.textio import normalized_text, text_bytes

from . import first_score_injection

if TYPE_CHECKING:
    from collections.abc import Mapping

SOURCE = "common/company_types/99_basic_companies.txt"
OUTPUT = "common/company_types/zz_sitai_company_ai_weights.txt"
DEFINE_SOURCE = first_score_injection.DEFINE_SOURCE
DEFINE = ("NAI", "COMPANY_TYPE_DEFAULT_BASE_WEIGHT")
SCORE = "ai_weight"
FROZEN_SHA256 = "8dae32317549ac05a31b016b08f57c063bd629d3a1a23c23ccfd9cdaa1d52b75"
MEMBER_SHA256 = "c5678d1baa434cd0abe6272af683ce9e55970342f9b8f9fc38ed74b13cb3e282"


PROJECTION = first_score_injection.Projection(
    SOURCE,
    OUTPUT,
    "company_types",
    "company_",
    SCORE,
    DEFINE,
    "1",
    "# Situated AI company candidate scores",
)


def render(
    adapters: decision_adapters.AdapterSet,
    *,
    inputs: Mapping[str, str],
    authority_lines: Mapping[str, int],
    reader_words: frozenset[str],
    model: compiler.SituatedModel,
) -> dict[str, str]:
    return first_score_injection.render(
        PROJECTION,
        adapters,
        inputs=inputs,
        authority_lines=authority_lines,
        reader_words=reader_words,
        model=model,
    )


def render_installation(installation: Path) -> dict[str, str]:
    """Verify the locked game, render from its checked inputs, then recheck those inputs."""
    installation = installation.absolute()
    game = installation / "game"
    executable = installation / "binaries" / "victoria3.exe"
    if (
        installation.resolve(strict=True) != installation
        or game.resolve(strict=True) != game
        or executable.resolve(strict=True) != executable
    ):
        raise ValueError("Installation, game directory and executable must be unlinked")

    r2_reader_authority.verify_installation(installation)
    defaults = json.loads(engine_scope.company_default_snapshot())
    companies = set(json.loads(engine_scope.company_snapshot())["script_hashes"])
    if first_score_injection._database_files(game, "company_types") != companies:
        raise ValueError("Installed company database does not match the reviewed source set")
    defines = first_score_injection._database_files(game, "defines")
    adapters = decision_adapters.load()
    sources = {source for source, _ in adapters.sources}
    names = sorted(sources | companies | defines | {DEFINE_SOURCE})
    distribution._validate_paths([*names, OUTPUT])
    raw = {source: native_authority_capture._source_bytes(game, source) for source in names}
    proof = engine_scope.company_default_evidence(game, raw)
    if not proof.verified:
        raise ValueError("Installed company sources or executable differ from the reviewed bytes")
    inputs = {source: normalized_text(data.decode("utf-8-sig")) for source, data in raw.items()}
    locked = decision_adapters.read_inputs(adapters, texts=inputs)
    readers = decision_adapters.reader_evidence(locked)
    files = render(
        adapters,
        inputs=inputs,
        authority_lines={row["id"]: row["line"] for row in defaults["implicit_companies"]},
        reader_words=frozenset(readers),
        model=compiler.load_model(),
    )
    if (
        first_score_injection._database_files(game, "company_types") != companies
        or first_score_injection._database_files(game, "defines") != defines
        or any(
            native_authority_capture._source_bytes(game, source) != raw[source] for source in names
        )
    ):
        raise ValueError("Installed source set or bytes changed during probe generation")
    r2_reader_authority.verify_installation(installation)
    return files


def verify_candidate(archive_path: Path, installation: Path | None = None) -> str:
    """Bind archive bytes to the reviewed candidate and optionally compare the live projection."""
    raw = archive_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != FROZEN_SHA256:
        raise ValueError("ZIP differs from the frozen D08 candidate")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        member = archive.read(OUTPUT)
    if hashlib.sha256(member).hexdigest() != MEMBER_SHA256:
        raise ValueError("ZIP company member differs from the reviewed company projection")
    if installation is not None:
        files = render_installation(installation)
        if files.keys() != {OUTPUT}:
            raise ValueError("Company renderer did not return exactly one original score file")
        # The compiler leaves a single space following the synthesized score opener.
        rendered = "\n".join(
            line.rstrip(" ") if line == "\tai_weight = { value = 1 " else line
            for line in normalized_text(files[OUTPUT]).split("\n")
        )
        if text_bytes(rendered, game=True) != member:
            raise ValueError("Installation render differs from the frozen company member")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path, help="Frozen D08 candidate ZIP")
    parser.add_argument("--installation", type=Path, help="Optional locked Victoria 3 installation")
    args = parser.parse_args()
    try:
        print(verify_candidate(args.archive, args.installation))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
