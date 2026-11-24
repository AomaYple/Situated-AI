"""Assemble the reviewed original company slice in a private candidate directory."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from pdx import company_injection, config, decision_adapters, decision_rules, distribution
from pdx.generation_transaction import GenerationTransaction
from pdx.localization_languages import DEFAULT_LANGUAGES, localization_path
from pdx.publishing import local
from pdx.situated import compiler, engine_scope, r2_reader_authority

IDENTITY = distribution.CandidateIdentity(
    mod_id="situated-ai-original-company",
    install_directory="Situated AI - Original Company Candidate",
)
VERSION = "0.1.0-rc.1"
GAME_VERSION = "1.15.2"
GAME_BUILD = "26763837"
COMPANY_COMMIT = "f51d97ede2f0b5bdd9218e4e7fed62a4e30889d7"
COMPANY_SOURCE_SHA256 = "ea890765d7a0d9c7954b40f28344f650fa288167f2af1f9ec71641bb7cc7ff7a"
# Canonical digest of the 15 payload hashes in the independent 6fdf7394 receipt.
REVIEWED_PAYLOAD = "33390176338333fbf1c64fd47081da7a13e79b5d14689679e41b325b6b0f04c7"
COVER_SHA256 = "d9dba46a83b9348372ad538e59c11badd1e4e7deae6a90e7fe6fecf68a77d2e8"
COMPANY_COUNT = 26
RULE_COUNT = 176
README = "README.md"
RECEIPT = "candidate-receipt.json"
ZIP_NAME = f"{IDENTITY.mod_id}-{VERSION}.zip"
LOCALIZATION_KEY = "SITAI_ORIGINAL_COMPANY_CANDIDATE_SCOPE"
LANGUAGE_PATHS = {
    language.directory: localization_path(language, "sitai_original_company_candidate")
    for language in DEFAULT_LANGUAGES
}
SCOPE_TEXT = {
    "braz_por": "Ajusta apenas a pontuação da IA para fundar 26 companhias básicas.",
    "english": "Adjusts only the AI score for founding 26 basic companies.",
    "french": "Ajuste uniquement le score de l’IA pour la création de 26 compagnies de base.",
    "german": "Passt nur die KI-Bewertung für die Gründung von 26 Standardunternehmen an.",
    "japanese": "26種類の基本企業を設立するときのAI評価だけを調整します。",
    "korean": "기본 회사 26종의 설립에 대한 AI 점수만 조정합니다.",
    "polish": "Zmienia wyłącznie ocenę SI przy zakładaniu 26 podstawowych kompanii.",
    "russian": "Меняет только оценку ИИ при основании 26 базовых компаний.",
    "simp_chinese": "仅调整 26 家基础公司成立时的 AI 评分。",
    "spanish": "Solo ajusta la puntuación de la IA para fundar 26 compañías básicas.",
    "turkish": "Yalnızca 26 temel şirketin kurulmasına ilişkin yapay zekâ puanını değiştirir.",
}


def _guide() -> str:
    path = f"Paradox Interactive/Victoria 3/mod/{IDENTITY.install_directory}"
    return (
        f"# {IDENTITY.install_directory}\n\n"
        f"本地候选 {VERSION} · Victoria 3 {GAME_VERSION} · Windows Steam 构建 {GAME_BUILD}\n\n"
        f"{SCOPE_TEXT['simp_chinese']} 3.4.0 的其他调整在此候选中恢复由原版处理。"
        "公司资格、投资和执行沿用原版。\n\n"
        f"退出游戏后，将 ZIP 解压到文档目录的 `{path}`。"
        "在启动器中为本候选创建独立 playset，禁用正式 Situated AI 及其他 Mod，再开新局。"
        "保留正式版本使用的存档和 playset。回退时退出游戏，切回原 playset 并读取对应旧存档。\n\n"
        f"{SCOPE_TEXT['english']} Other changes from 3.4.0 revert to vanilla in this candidate. "
        "Company eligibility, investment and execution follow vanilla rules.\n\n"
        f"Exit the game and extract the ZIP to `{path}` in your documents folder. "
        "Use a separate launcher playset with this candidate as its only mod and start a new game. "
        "Keep the previous playset and its saves. To revert, exit the game, return to that playset "
        "and load the corresponding save.\n\n"
        "## 功能范围 / Scope by language\n\n"
        + "".join(f"- {language}: {SCOPE_TEXT[language]}\n" for language in LANGUAGE_PATHS)
    )


def _payload(text: str, cover: bytes) -> dict[str, str | bytes]:
    if SCOPE_TEXT.keys() != LANGUAGE_PATHS.keys():
        raise ValueError("Candidate scope text must cover the locked language set")
    distribution._validate_thumbnail(cover)
    if hashlib.sha256(cover).hexdigest() != COVER_SHA256:
        raise ValueError("Candidate launcher cover differs from the repository-owned asset")
    metadata = distribution.launcher_metadata(
        {
            "name": IDENTITY.install_directory,
            "id": IDENTITY.mod_id,
            "version": VERSION,
            "supported_game_version": GAME_VERSION,
            "short_description": SCOPE_TEXT["simp_chinese"],
            "picture": distribution.THUMBNAIL_NAME,
            "tags": [],
            "relationships": [],
            "game_custom_data": {"multiplayer_synchronized": True},
        }
    )
    return {
        company_injection.OUTPUT: text,
        distribution.METADATA_NAME: json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        distribution.THUMBNAIL_NAME: cover,
        README: _guide(),
        **{
            LANGUAGE_PATHS[language.directory]: (
                f"{language.header}:\n {LOCALIZATION_KEY}: "
                f"{json.dumps(SCOPE_TEXT[language.directory], ensure_ascii=False)}\n"
            )
            for language in DEFAULT_LANGUAGES
        },
    }


def _company_text() -> str:
    """Compile only the reviewed source's rules into newly authored score containers."""
    r2_reader_authority.verify_installation(config.ROOT)
    adapters = decision_adapters.load()
    source = company_injection.SOURCE
    paths = dict(adapters.sources)
    company_injection.verify_database_sources(config.GAME, paths)
    engine_scope.verify_company_defaults_game(config.GAME)
    inputs = decision_adapters.read_inputs(adapters, game=config.GAME)
    model = compiler.load_model()
    policy = dict(adapters.policies)[source]
    if len(policy.rules) != RULE_COUNT or len(policy.groups()) != COMPANY_COUNT:
        raise ValueError("Company policy differs from the reviewed 26 companies and 176 rules")
    shell = company_injection.make_shell(
        policy,
        policy.enabled_domains,
        [item for item in adapters.initial_values if item.source == source],
        inputs,
    )
    compiled, _ = compiler.compile_policy(policy, source, model)
    rendered = decision_rules.patch(
        shell,
        compiled,
        baseline=inputs[source],
        default_strategy=False,
        reader_words=frozenset(decision_adapters.reader_evidence(inputs)),
        consumer_ir=model.consumer_ir,
        consumer_source=source,
    )
    text = company_injection.render_injections(rendered, policy)
    text = "\n".join(
        line.rstrip(" ") if line == "\tai_weight = { value = 1 " else line
        for line in text.split("\n")
    )
    if hashlib.sha256(text.encode()).hexdigest() != COMPANY_SOURCE_SHA256:
        raise ValueError(
            "Company projection differs from the independently reviewed original bytes"
        )
    company_injection.verify_database_sources(config.GAME, paths)
    engine_scope.verify_company_defaults_game(config.GAME)
    if decision_adapters.read_inputs(adapters, game=config.GAME) != inputs:
        raise ValueError("Locked adapter inputs changed while compiling the candidate")
    r2_reader_authority.verify_installation(config.ROOT)
    return text


def _json(document: object) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _check_frozen(root: Path, expected: dict[str, bytes]) -> None:
    actual = distribution._profile_directory_files(root)
    if set(actual) != set(expected):
        raise ValueError(f"Frozen candidate has missing or unknown files: {root}")
    if local.tree(root) != local._expected_tree(expected):
        raise ValueError(f"Frozen candidate bytes or directory topology changed: {root}")


def _freeze(
    root: Path,
    files: dict[str, str | bytes],
    *,
    reviewed_digest: str,
    origins: dict[str, str],
    generation: dict[str, object],
    identity: distribution.CandidateIdentity,
    zip_name: str,
) -> Path:
    """Stage only admitted outputs and publish a complete immutable directory by exclusive rename."""
    members = distribution.payloads(files)
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in members.items()}
    document = json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    if origins.keys() != members.keys() or hashlib.sha256(document).hexdigest() != reviewed_digest:
        raise ValueError("Candidate payload or provenance differs from independent admission")
    distribution._validate_paths([zip_name, RECEIPT, identity.install_directory])
    if "/" in zip_name or not zip_name.endswith(".zip") or zip_name == identity.install_directory:
        raise ValueError("Invalid frozen candidate archive name")
    root = local.checked_path(root.absolute())
    if root.resolve().as_posix() != root.as_posix():
        raise ValueError("Candidate output root must use its physical path spelling")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=".build-") as temporary:
        staged = Path(temporary) / "candidate"
        staged.mkdir()
        archive = distribution.write_zip(
            files,
            staged / zip_name,
            generation=generation,
            candidate=identity,
        )
        raw = archive.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(archive) as reader:
            manifest = reader.read(distribution.MANIFEST_NAME)
        installed = {**members, distribution.MANIFEST_NAME: manifest}
        receipt = _json(
            {
                "schema": 1,
                "archive_sha256": digest,
                "payload_review_sha256": reviewed_digest,
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                "members": {
                    name: {"delivery_sha256": hashes[name], "origin": origins[name]}
                    for name in sorted(hashes)
                },
                "generation": generation,
                "runtime": "not_run",
            }
        )
        expected = {
            f"{identity.install_directory}/{name}": data for name, data in installed.items()
        }
        with GenerationTransaction() as transaction:
            transaction.replace(
                {staged / key: data for key, data in {**expected, RECEIPT: receipt}.items()}
            )
            expected.update({zip_name: raw, RECEIPT: receipt})
            _check_frozen(staged, expected)
        frozen = root / digest
        try:
            local._rename_exclusive(staged, frozen)
        except OSError:
            if not frozen.is_dir():
                raise
            # Concurrent or resumed builds may only reuse the identical full result.
            _check_frozen(frozen, expected)
        return frozen / zip_name


def build() -> Path:
    files = _payload(
        _company_text(), (config.REPO / "mod" / distribution.THUMBNAIL_NAME).read_bytes()
    )
    origins = {
        company_injection.OUTPUT: f"{COMPANY_COMMIT}:company_injection.render_injections",
        distribution.METADATA_NAME: "pdx.original_candidate._payload / launcher_metadata",
        distribution.THUMBNAIL_NAME: "53ce21be:mod/thumbnail.png",
        README: "pdx.original_candidate._guide",
        **{
            name: f"pdx.original_candidate.SCOPE_TEXT[{lang}]"
            for lang, name in LANGUAGE_PATHS.items()
        },
    }
    return _freeze(
        config.OUT / "original-standard",
        files,
        reviewed_digest=REVIEWED_PAYLOAD,
        origins=origins,
        generation={
            "schema": "situated-ai-original-candidate/1",
            "publication_channel": "local_candidate",
            "game_build": GAME_BUILD,
            "reference_release": "3.4.0",
            "company_fields": COMPANY_COUNT,
            "company_rules": RULE_COUNT,
            "remaining_writers": 955,
            "fiscal_mode": "absent_new_game_only",
            "runtime": "not_run",
            "source_projection_sha256": COMPANY_SOURCE_SHA256,
            "reviewed_payload_sha256": REVIEWED_PAYLOAD,
        },
        identity=IDENTITY,
        zip_name=ZIP_NAME,
    )
