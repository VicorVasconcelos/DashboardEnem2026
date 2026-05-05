from __future__ import annotations

import io
import hashlib
import re
import unicodedata
from datetime import datetime
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


_PROCESS_CACHE: dict[str, Any] = {
    "fingerprint": None,
    "result": None,
}


@dataclass
class ProcessResult:
    metrics: dict[str, Any]
    charts: dict[str, Any]
    substitution_log: list[dict[str, Any]]
    totals_by_role: list[dict[str, Any]]
    municipality_gaps: list[dict[str, Any]]
    municipality_base_by_uf: list[dict[str, Any]]
    coordinator_by_city: list[dict[str, Any]]
    returning_municipals: list[dict[str, Any]]
    role_changes: list[dict[str, Any]]
    requirements_issues: list[dict[str, Any]]
    municipalities_without_coordinator: list[dict[str, Any]]
    all_collaborators: list[dict[str, Any]]


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _to_number(series: pd.Series) -> pd.Series:
    if isinstance(series, pd.DataFrame):
        series = series.replace("", pd.NA).bfill(axis=1).iloc[:, 0]

    cleaned = (
        series.astype("string")
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
        .str.replace(r"[^0-9.-]", "", regex=True)
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def _is_excel(filename: str) -> bool:
    return filename.lower().endswith((".xlsx", ".xls"))


def _read_content(name: str, content: bytes) -> pd.DataFrame:
    if not content:
        return pd.DataFrame()

    buffer = io.BytesIO(content)

    if _is_excel(name):
        try:
            if "alocacao" in _normalize_text(name):
                return pd.read_excel(buffer, sheet_name="Alocacoes", header=4)
        except Exception:
            buffer.seek(0)
        return pd.read_excel(buffer)

    return pd.read_csv(io.StringIO(content.decode("utf-8", errors="ignore")), sep=None, engine="python")


def _read_upload_path(file_path: Path) -> pd.DataFrame:
    return _read_content(file_path.name, file_path.read_bytes())


def _rename_columns(df: pd.DataFrame, mapping: dict[str, list[str]]) -> pd.DataFrame:
    cols_norm = {c: _normalize_text(c) for c in df.columns}
    rename_map: dict[str, str] = {}

    for original, normalized in cols_norm.items():
        for target, aliases in mapping.items():
            if any(alias in normalized for alias in aliases):
                rename_map[original] = target
                break

    renamed = df.rename(columns=rename_map)

    if not renamed.columns.duplicated().any():
        return renamed

    collapsed = pd.DataFrame(index=renamed.index)
    for column_name in dict.fromkeys(renamed.columns):
        selected = renamed.loc[:, renamed.columns == column_name]
        if isinstance(selected, pd.DataFrame) and selected.shape[1] > 1:
            collapsed[column_name] = selected.replace("", pd.NA).bfill(axis=1).iloc[:, 0]
        else:
            collapsed[column_name] = renamed[column_name]

    return collapsed


def _canonical_role(value: Any) -> str:
    role = str(value or "").strip()
    norm = _normalize_text(role)

    if "assistente" in norm:
        if "municipal" in norm or any(
            token in norm
            for token in ["coordenador_municipal", "coordenadora_municipal", "coordenacao_municipal", "coord_municipal"]
        ):
            return "Assistente de Coordenador Municipal"
        if "estadual" in norm or any(
            token in norm
            for token in ["coordenador_estadual", "coordenadora_estadual", "coordenacao_estadual", "coord_estadual"]
        ):
            return "Assistente de Coordenador Estadual"
        return "Assistente"

    if "municipal" in norm or any(
        token in norm
        for token in ["coordenador_municipal", "coordenadora_municipal", "coordenacao_municipal", "coord_municipal", "coordenador_municipail"]
    ):
        return "Coordenador Municipal"
    if "estadual" in norm or any(
        token in norm for token in ["coordenador_estadual", "coordenadora_estadual", "coordenacao_estadual", "coord_estadual"]
    ):
        return "Coordenador Estadual"
    return role


def _deduplicate_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    subset: list[str] = []
    for column in ["CPF", "cpf", "nome", "ano", "funcao", "uf", "cidade"]:
        if column in df.columns and column not in subset:
            subset.append(column)

    if subset:
        return df.drop_duplicates(subset=subset).reset_index(drop=True)

    return df.drop_duplicates().reset_index(drop=True)


def _extract_year(text: Any) -> int | None:
    match = re.search(r"(20\d{2})", str(text or ""))
    if not match:
        return None
    year = int(match.group(1))
    if 2000 <= year <= 2100:
        return year
    return None


def _extract_year_series(series: pd.Series) -> pd.Series:
    return series.apply(_extract_year)


def _extract_file_year(file_name: str) -> int | None:
    return _extract_year(file_name)


def _with_year_column(df: pd.DataFrame, file_name: str, candidates: list[str]) -> pd.DataFrame:
    out = df.copy()
    year_series = pd.Series([None] * len(out), index=out.index, dtype="object")

    for column in candidates:
        if column in out.columns:
            candidate_year = _extract_year_series(_column_as_series(out, column))
            year_series = year_series.combine_first(candidate_year)

    fallback = _extract_file_year(file_name)
    current_year = datetime.now().year
    if fallback is None or fallback < current_year:
        fallback = current_year

    year_series = year_series.fillna(fallback)

    out["ano"] = pd.to_numeric(year_series, errors="coerce").astype("Int64")
    return out


def _column_as_series(df: pd.DataFrame, column: str, default: Any = "") -> pd.Series:
    if column not in df.columns:
        return pd.Series([default] * len(df), index=df.index)

    value = df[column]
    if isinstance(value, pd.DataFrame):
        return value.replace("", pd.NA).bfill(axis=1).iloc[:, 0].fillna(default)
    return value.fillna(default)


def _is_veteran(value: Any) -> bool:
    norm = _normalize_text(value)
    return norm in {
        "veterano",
        "sim",
        "s",
        "true",
        "1",
        "experiente",
        "ja_participou",
        "participou",
    }


def _person_key(row: pd.Series) -> str:
    cpf = re.sub(r"\D", "", str(row.get("CPF", "") or ""))
    if cpf:
        return cpf[:11]
    return _normalize_text(row.get("nome", ""))


def _normalize_cpf_digits(value: Any) -> str:
    """Normaliza CPF para exatamente 11 dígitos, preenchendo com zeros à esquerda se necessário."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    # Completa com zeros à esquerda até 11 dígitos, depois trunca se necessário
    return digits.zfill(11)[:11]

def _normalize_ibge_code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    return digits.zfill(7)


def _extract_experience_count(value: Any) -> int | None:
    norm = _normalize_text(value)
    if not norm:
        return None
    if "mais_de_5" in norm:
        return 6
    match = re.search(r"(\d+)", norm)
    if match:
        return int(match.group(1))
    return None


def _is_higher_education(value: Any) -> bool:
    norm = _normalize_text(value)
    if not norm:
        return False
    if "pos_graduando" in norm:
        return True
    if "graduando" in norm:
        return False
    accepted_tokens = [
        "graduado",
        "ensino_superior",
        "superior_completo",
        "especialista",
        "pos_graduado",
        "pos_graduacao",
        "mestre",
        "doutor",
    ]
    return any(token in norm for token in accepted_tokens)


def _is_trained(value: Any) -> bool:
    return _normalize_text(value) in {"sim", "s", "true", "1", "capacitado", "aprovado"}


def _build_people_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["person_key", "nome", "CPF", "uf", "cidade", "funcao"])

    people = df.copy()
    people["person_key"] = people.apply(_person_key, axis=1)
    people = people[people["person_key"].astype(str).str.strip() != ""].copy()
    if people.empty:
        return pd.DataFrame(columns=["person_key", "nome", "CPF", "uf", "cidade", "funcao"])

    people["nome_norm"] = people["nome"].map(_normalize_text) if "nome" in people.columns else ""
    people = people.sort_values(["person_key", "nome_norm", "uf", "cidade", "funcao"])
    return people.groupby("person_key", as_index=False).first()


def _load_municipality_base(reports_dir: Path) -> pd.DataFrame:
    municipalities_file = reports_dir / "Municípios.xlsx"
    if not municipalities_file.exists():
        return pd.DataFrame(columns=["uf", "cidade", "cidade_norm", "codigo_ibge"])

    try:
        try:
            df_municipios = pd.read_excel(municipalities_file, sheet_name="Municipios de 2025")
        except Exception:
            df_municipios = pd.read_excel(municipalities_file)
    except Exception:
        return pd.DataFrame(columns=["uf", "cidade", "cidade_norm", "codigo_ibge"])

    if df_municipios.empty:
        return pd.DataFrame(columns=["uf", "cidade", "cidade_norm", "codigo_ibge"])

    df_municipios.columns = [_normalize_text(c) for c in df_municipios.columns]
    if not {"uf", "cidade"}.issubset(df_municipios.columns):
        return pd.DataFrame(columns=["uf", "cidade", "cidade_norm", "codigo_ibge"])

    base_columns = ["uf", "cidade"]
    if "codigo_do_ibge" in df_municipios.columns:
        base_columns.append("codigo_do_ibge")

    base = df_municipios[base_columns].dropna(subset=["uf", "cidade"]).assign(
        uf=lambda frame: frame["uf"].astype(str).str.strip().str.upper(),
        cidade=lambda frame: frame["cidade"].astype(str).str.strip(),
    )
    if "codigo_do_ibge" in base.columns:
        base["codigo_ibge"] = base["codigo_do_ibge"].map(_normalize_ibge_code)
        base = base.drop(columns=["codigo_do_ibge"])
    else:
        base["codigo_ibge"] = ""
    base["cidade_norm"] = base["cidade"].map(_normalize_text)
    base = base[(base["uf"] != "") & (base["cidade_norm"] != "")]
    return base.drop_duplicates(subset=["uf", "cidade_norm", "codigo_ibge"]).reset_index(drop=True)


def _build_municipality_coverage(
    df_ind_current: pd.DataFrame,
    reports_dir: Path,
    reference_year: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int | None]]:
    coord_roles = {"Coordenador Estadual", "Coordenador Municipal"}
    municipal_roles = {"Coordenador Municipal"}

    if not df_ind_current.empty and {"uf", "cidade", "funcao"}.issubset(df_ind_current.columns):
        coord_current = df_ind_current[df_ind_current["funcao"].isin(coord_roles)].copy()
        municipal_current = df_ind_current[df_ind_current["funcao"].isin(municipal_roles)].copy()
    else:
        coord_current = pd.DataFrame(columns=["uf", "cidade", "funcao"])
        municipal_current = pd.DataFrame(columns=["uf", "cidade", "funcao"])

    if not coord_current.empty:
        coord_current = coord_current.copy()
        if "codigo_ibge" in coord_current.columns:
            coord_current["codigo_ibge"] = coord_current["codigo_ibge"].map(_normalize_ibge_code)
        else:
            coord_current["codigo_ibge"] = ""
        city_counts = (
            coord_current.groupby(["uf", "cidade"], as_index=False)
            .agg(
                total_coordenadores=("funcao", "size"),
                coordenadores_estaduais=("funcao", lambda s: int((s == "Coordenador Estadual").sum())),
                coordenadores_municipais=("funcao", lambda s: int((s == "Coordenador Municipal").sum())),
            )
            .sort_values(["uf", "cidade"])
        )
        city_count_records = city_counts.to_dict("records")
    else:
        city_count_records = []

    reference_cities = _load_municipality_base(reports_dir)
    if reference_cities.empty:
        return [], [], city_count_records, {"reference_year": reference_year, "total_reference_cities": 0, "covered_cities": 0}

    reference_by_uf = (
        reference_cities.groupby("uf", as_index=False)
        .agg(qtd_municipios_base=("cidade", "nunique"))
        .sort_values("uf")
        .to_dict("records")
    )
    current_municipal_cities = (
        municipal_current[["uf", "cidade"]]
        .dropna()
        .assign(
            uf=lambda frame: frame["uf"].astype(str).str.strip().str.upper(),
            cidade=lambda frame: frame["cidade"].astype(str).str.strip(),
        )
        .drop_duplicates()
    )
    if "codigo_ibge" in municipal_current.columns:
        current_municipal_cities = current_municipal_cities.merge(
            municipal_current[["uf", "cidade", "codigo_ibge"]].drop_duplicates(),
            on=["uf", "cidade"],
            how="left",
        )
        current_municipal_cities["codigo_ibge"] = current_municipal_cities["codigo_ibge"].map(_normalize_ibge_code)
    else:
        current_municipal_cities["codigo_ibge"] = ""
    current_municipal_cities["cidade_norm"] = current_municipal_cities["cidade"].map(_normalize_text)

    current_codes = set(current_municipal_cities["codigo_ibge"].dropna().astype(str)) - {""}
    current_city_keys = set(
        (str(row["uf"]).strip().upper(), str(row["cidade_norm"]).strip())
        for _, row in current_municipal_cities[["uf", "cidade_norm"]].drop_duplicates().iterrows()
    )

    def _reference_is_missing(row: pd.Series) -> bool:
        codigo_ibge = _normalize_ibge_code(row.get("codigo_ibge", ""))
        if codigo_ibge and codigo_ibge in current_codes:
            return False
        return (str(row["uf"]).strip().upper(), str(row["cidade_norm"]).strip()) not in current_city_keys

    missing = reference_cities[reference_cities.apply(_reference_is_missing, axis=1)].copy()

    gap_records: list[dict[str, Any]] = []
    municipal_count_by_uf = (
        municipal_current.groupby("uf", as_index=False)
        .agg(qtd_indicados_municipal=("cidade", "size"))
        if not municipal_current.empty and {"uf", "cidade"}.issubset(municipal_current.columns)
        else pd.DataFrame(columns=["uf", "qtd_indicados_municipal"])
    )
    municipal_count_map = {
        str(row["uf"]).strip().upper(): int(row["qtd_indicados_municipal"])
        for _, row in municipal_count_by_uf.iterrows()
        if pd.notna(row.get("uf"))
    }

    if not missing.empty:
        grouped = missing.groupby("uf")["cidade"].apply(lambda values: sorted(set(values))).reset_index()
        for _, row in grouped.iterrows():
            uf = str(row["uf"]).strip().upper()
            cities = row["cidade"]

            # No DF, a operação usa contagem de coordenadores municipais indicados
            # versus quantidade base de municípios da planilha operacional.
            if uf == "DF":
                base_count = int(reference_cities[reference_cities["uf"] == "DF"].shape[0])
                indicated_count = int(municipal_count_map.get("DF", 0))
                missing_count = max(base_count - indicated_count, 0)
                if missing_count == 0:
                    continue
                cities = cities[:missing_count] if cities else ["Municipio pendente"] * missing_count

            gap_records.append(
                {
                    "uf": uf,
                    "qtd_municipios_sem_coordenador": len(cities),
                    "municipios": ", ".join(cities),
                }
            )

    return (
        gap_records,
        reference_by_uf,
        city_count_records,
        {
            "reference_year": reference_year,
            "total_reference_cities": int(len(reference_cities)),
            "covered_cities": int(len(current_municipal_cities)),
        },
    )


def _build_year_transition_views(
    df_ind: pd.DataFrame,
    current_year: int | None,
    previous_year: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if current_year is None or previous_year is None or df_ind.empty:
        return [], []

    current = _slice_by_year(df_ind, current_year)
    previous = _slice_by_year(df_ind, previous_year)
    if current.empty or previous.empty:
        return [], []

    current_people = _build_people_snapshot(current)
    previous_people = _build_people_snapshot(previous)
    if current_people.empty or previous_people.empty:
        return [], []

    comparison = current_people.merge(previous_people, on="person_key", how="inner", suffixes=("_current", "_previous"))
    if comparison.empty:
        return [], []

    returning_municipals = comparison[
        (comparison["funcao_current"] == "Coordenador Municipal")
        & (comparison["funcao_previous"] == "Coordenador Municipal")
    ].copy()

    role_changes = comparison[comparison["funcao_current"] != comparison["funcao_previous"]].copy()

    returning_records = (
        returning_municipals[
            ["nome_current", "CPF_current", "uf_current", "cidade_current", "funcao_previous", "funcao_current"]
        ]
        .rename(
            columns={
                "nome_current": "nome",
                "CPF_current": "cpf",
                "uf_current": "uf",
                "cidade_current": "cidade",
                "funcao_previous": "funcao_2025",
                "funcao_current": "funcao_2026",
            }
        )
        .sort_values(["uf", "cidade", "nome"])
        .to_dict("records")
    )

    role_change_records = (
        role_changes[
            ["nome_current", "CPF_current", "uf_current", "cidade_current", "funcao_previous", "funcao_current"]
        ]
        .rename(
            columns={
                "nome_current": "nome",
                "CPF_current": "cpf",
                "uf_current": "uf",
                "cidade_current": "cidade",
                "funcao_previous": "funcao_2025",
                "funcao_current": "funcao_2026",
            }
        )
        .sort_values(["funcao_2025", "funcao_2026", "nome"])
        .to_dict("records")
    )

    return returning_records, role_change_records


def _build_requirements_audit(df_ind_current: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if df_ind_current.empty:
        return [], {
            "coordenadores_avaliados": 0,
            "sem_formacao_necessaria": 0,
            "fora_regra_experiencia": 0,
            "sem_capacitacao": 0,
            "nao_conformes": 0,
        }

    requirements = {
        "Coordenador Estadual": {"min_experience": 5},
        "Coordenador Municipal": {"min_experience": 4},
    }
    coords = df_ind_current[df_ind_current["funcao"].isin(requirements.keys())].copy()
    if coords.empty:
        return [], {
            "coordenadores_avaliados": 0,
            "sem_formacao_necessaria": 0,
            "fora_regra_experiencia": 0,
            "sem_capacitacao": 0,
            "nao_conformes": 0,
        }

    records: list[dict[str, Any]] = []
    formation_failures = 0
    experience_failures = 0
    training_failures = 0

    for _, row in coords.iterrows():
        role = str(row.get("funcao", "")).strip()
        cfg = requirements.get(role)
        if cfg is None:
            continue

        escolaridade = row.get("Escolaridade")
        experiencia = row.get("experiencia")
        capacitado = row.get("Capacitado")
        exp_count = _extract_experience_count(experiencia)
        formacao_ok = _is_higher_education(escolaridade)
        experiencia_ok = exp_count is not None and exp_count >= cfg["min_experience"]
        capacitacao_ok = _is_trained(capacitado)

        if not formacao_ok:
            formation_failures += 1
        if not experiencia_ok:
            experience_failures += 1
        if not capacitacao_ok:
            training_failures += 1

        pending: list[str] = []
        if not formacao_ok:
            pending.append("Formacao")
        if not experiencia_ok:
            pending.append("Experiencia")
        if not capacitacao_ok:
            pending.append("Capacitacao")

        if not pending:
            continue

        records.append(
            {
                "nome": row.get("nome"),
                "cpf": row.get("CPF"),
                "uf": row.get("uf"),
                "cidade": row.get("cidade"),
                "funcao": role,
                "escolaridade": escolaridade,
                "experiencia": experiencia,
                "experiencia_minima": cfg["min_experience"],
                "capacitado": capacitado,
                "formacao_ok": "Sim" if formacao_ok else "Nao",
                "experiencia_ok": "Sim" if experiencia_ok else "Nao",
                "capacitacao_ok": "Sim" if capacitacao_ok else "Nao",
                "pendencias": ", ".join(pending),
            }
        )

    return (
        sorted(records, key=lambda item: (str(item.get("funcao", "")), str(item.get("uf", "")), str(item.get("cidade", "")), str(item.get("nome", "")))),
        {
            "coordenadores_avaliados": int(len(coords)),
            "sem_formacao_necessaria": int(formation_failures),
            "fora_regra_experiencia": int(experience_failures),
            "sem_capacitacao": int(training_failures),
            "nao_conformes": int(len(records)),
        },
    )


def _prepare_alocacao(df: pd.DataFrame, file_name: str) -> pd.DataFrame:
    mapping = {
        "uf": ["uf", "estado", "sg_uf", "unidade_federativa"],
        "cidade": ["cidade", "municipio"],
        "funcao": ["funcao", "cargo", "perfil", "papel"],
        "previstos": ["previstos"],
        "alocados": ["alocados"],
        "data_turno": ["data_turno", "data/turno"],
    }
    out = _rename_columns(df, mapping)

    if "funcao" in out.columns:
        out["funcao"] = _column_as_series(out, "funcao").astype(str).str.strip().apply(_canonical_role)

    if "previstos" in out.columns:
        out["previstos"] = _to_number(_column_as_series(out, "previstos"))
    else:
        out["previstos"] = 0

    if "alocados" in out.columns:
        out["alocados"] = _to_number(_column_as_series(out, "alocados"))
    else:
        out["alocados"] = 0

    out["deficit"] = (out["previstos"] - out["alocados"]).clip(lower=0)

    if "uf" in out.columns:
        out["uf"] = _column_as_series(out, "uf").astype(str).str.upper().str.strip()
    if "cidade" in out.columns:
        out["cidade"] = _column_as_series(out, "cidade").astype(str).str.strip()

    out = _with_year_column(out, file_name, ["data_turno", "funcao"])
    return out


def _prepare_indicados(df: pd.DataFrame, file_name: str) -> pd.DataFrame:
    mapping = {
        "uf": ["uf", "estado", "sg_uf"],
        "cidade": ["cidade", "municipio"],
        "codigo_ibge": ["codigoibge", "codigo_do_ibge"],
        "nome": ["nome"],
        "funcao": ["funcao", "cargo", "papel"],
        "experiencia": ["experiencia"],
        "indicado_em": ["indicado_em", "indicado em"],
        "substituido": ["substituido"],
    }
    out = _rename_columns(df, mapping)

    if "funcao" in out.columns:
        out["funcao"] = _column_as_series(out, "funcao").astype(str).str.strip().apply(_canonical_role)

    if "uf" in out.columns:
        out["uf"] = _column_as_series(out, "uf").astype(str).str.upper().str.strip()
    if "cidade" in out.columns:
        out["cidade"] = _column_as_series(out, "cidade").astype(str).str.strip()
    if "codigo_ibge" in out.columns:
        out["codigo_ibge"] = _column_as_series(out, "codigo_ibge").map(_normalize_ibge_code)

    out["is_veteran"] = _column_as_series(out, "experiencia").apply(_is_veteran) if "experiencia" in out.columns else False

    out = _with_year_column(out, file_name, ["funcao", "indicado_em"])
    return out


def _split_files(file_paths: list[Path]) -> tuple[list[pd.DataFrame], list[pd.DataFrame]]:
    alocacao_frames: list[pd.DataFrame] = []
    indicados_frames: list[pd.DataFrame] = []

    for file_path in file_paths:
        name = file_path.name
        df = _read_upload_path(file_path)
        if df.empty:
            continue

        norm_name = _normalize_text(name)
        if "alocacao" in norm_name:
            alocacao_frames.append(_prepare_alocacao(df, name))
        elif "indicado" in norm_name:
            indicados_frames.append(_prepare_indicados(df, name))
        else:
            if "municipio" in norm_name:
                continue
            if "alocados" in {_normalize_text(c) for c in df.columns}:
                alocacao_frames.append(_prepare_alocacao(df, name))
            else:
                indicados_frames.append(_prepare_indicados(df, name))

    return alocacao_frames, indicados_frames


def _find_report_files(reports_dir: Path) -> list[Path]:
    allowed = {".xlsx", ".xls", ".csv"}
    return sorted(
        [
            path
            for path in reports_dir.iterdir()
            if path.is_file() 
            and path.suffix.lower() in allowed
            and not path.name.startswith("~$")
        ],
        key=lambda path: path.name.lower(),
    )


def _infer_reference_year(*frames: pd.DataFrame, default_year: int | None = None) -> int:
    years: list[int] = []

    for frame in frames:
        if frame.empty or "ano" not in frame.columns:
            continue

        valid_years = pd.to_numeric(frame["ano"], errors="coerce").dropna().astype(int)
        years.extend(int(year) for year in valid_years.unique())

    if years:
        return max(years)

    if default_year is not None:
        return default_year

    return datetime.now().year


def _build_substitution_log(df_ind: pd.DataFrame) -> list[dict[str, Any]]:
    if df_ind.empty or "substituido" not in df_ind.columns:
        return []

    substituido_series = _column_as_series(df_ind, "substituido", default=pd.NA)
    normalized_sub = substituido_series.apply(
        lambda value: "" if pd.isna(value) else str(value).strip().lower()
    )
    invalid_tokens = {"", "nan", "none", "null", "na", "n/a", "-", "--"}
    base = df_ind[~normalized_sub.isin(invalid_tokens)].copy()
    if base.empty:
        return []

    result = []
    for _, row in base.iterrows():
        substituido_value = row.get("substituido", pd.NA)
        if pd.isna(substituido_value):
            continue

        substituido_text = str(substituido_value).strip()
        if not substituido_text or substituido_text.lower() in invalid_tokens:
            continue

        novo_alocado_text = str(row.get("nome", "")).strip()
        if _normalize_text(substituido_text) == _normalize_text(novo_alocado_text):
            continue

        result.append(
            {
                "substituido": substituido_text,
                "novo_alocado": novo_alocado_text,
                "funcao": str(row.get("funcao", "")).strip(),
                "uf": str(row.get("uf", "")).strip(),
                "cidade": str(row.get("cidade", "")).strip(),
                "ano": int(row.get("ano")) if pd.notna(row.get("ano")) else None,
            }
        )

    return result


def _build_municipalities_without_coordinator(df_ind: pd.DataFrame, reports_dir: Path) -> list[dict[str, Any]]:
    """
    Cruzar a lista de municípios com indicados para identificar quais NÃO possuem coordenador municipal.
    """
    try:
        reference_cities = _load_municipality_base(reports_dir)
        if reference_cities.empty:
            return []

        # Filtrar apenas coordenadores municipais do df_ind
        if df_ind.empty or "funcao" not in df_ind.columns:
            return []

        coord_municipais = df_ind[df_ind["funcao"] == "Coordenador Municipal"].copy()
        
        if coord_municipais.empty:
            # Se não há coordenadores municipais, todos os municípios estão "sem coordenador"
            # Mas não faz sentido retornar todos. Retorna vazio.
            return []

        # Normalizar dados dos coordenadores
        coord_municipais["uf"] = coord_municipais["uf"].astype(str).str.upper().str.strip()
        coord_municipais["cidade"] = coord_municipais["cidade"].astype(str).str.strip()
        coord_municipais["cidade_norm"] = coord_municipais["cidade"].map(_normalize_text)
        if "codigo_ibge" in coord_municipais.columns:
            coord_municipais["codigo_ibge"] = coord_municipais["codigo_ibge"].map(_normalize_ibge_code)
        else:
            coord_municipais["codigo_ibge"] = ""

        coord_codes = set(coord_municipais["codigo_ibge"].dropna().astype(str)) - {""}
        coord_city_keys = set(
            (str(row["uf"]).strip().upper(), str(row["cidade_norm"]).strip())
            for _, row in coord_municipais[["uf", "cidade_norm"]].drop_duplicates().iterrows()
        )

        def _reference_has_coord(row: pd.Series) -> bool:
            codigo_ibge = _normalize_ibge_code(row.get("codigo_ibge", ""))
            if codigo_ibge and codigo_ibge in coord_codes:
                return True
            return (str(row["uf"]).strip().upper(), str(row["cidade_norm"]).strip()) in coord_city_keys

        # Encontrar cidades SEM coordenador - cruzamento por Código IBGE com fallback por cidade normalizada
        missing = reference_cities[~reference_cities.apply(_reference_has_coord, axis=1)].copy()

        municipal_count_by_uf = (
            coord_municipais.groupby("uf", as_index=False)
            .agg(qtd_indicados_municipal=("cidade", "size"))
            if not coord_municipais.empty and {"uf", "cidade"}.issubset(coord_municipais.columns)
            else pd.DataFrame(columns=["uf", "qtd_indicados_municipal"])
        )
        municipal_count_map = {
            str(row["uf"]).strip().upper(): int(row["qtd_indicados_municipal"])
            for _, row in municipal_count_by_uf.iterrows()
            if pd.notna(row.get("uf"))
        }

        # Agrupar por UF
        grouped_by_uf = {}
        for _, item in missing.iterrows():
            uf = str(item["uf"]).strip().upper()
            if uf not in grouped_by_uf:
                grouped_by_uf[uf] = []
            grouped_by_uf[uf].append(item["cidade"])

        # Regra operacional para DF: usar quantidade base menos quantidade indicada.
        if "DF" in grouped_by_uf:
            base_df_count = int(reference_cities[reference_cities["uf"] == "DF"].shape[0])
            indicated_df_count = int(municipal_count_map.get("DF", 0))
            missing_df_count = max(base_df_count - indicated_df_count, 0)

            if missing_df_count == 0:
                grouped_by_uf.pop("DF", None)
            else:
                grouped_by_uf["DF"] = grouped_by_uf["DF"][:missing_df_count]

        # Retornar em formato resumido
        return [
            {
                "uf": uf,
                "qtd_municipios_sem_coordenador": len(cidades),
                "municipios": sorted(cidades),
            }
            for uf, cidades in sorted(grouped_by_uf.items())
        ]
    
    except PermissionError:
        # Arquivo bloqueado (aberto no Excel) - retorna vazio
        return []
    except Exception as e:
        # Qualquer outro erro - retorna vazio para não quebrar o dashboard
        import traceback
        traceback.print_exc()
        return []


def _build_fingerprint(file_paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha1()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    processor_file = Path(__file__).resolve()
    processor_signature = (
        "__processor__",
        int(processor_file.stat().st_mtime_ns),
        int(processor_file.stat().st_size),
        _file_hash(processor_file),
    )
    file_signature = tuple(
        (path.name, int(path.stat().st_mtime_ns), int(path.stat().st_size), _file_hash(path))
        for path in file_paths
    )
    return (processor_signature, *file_signature)


def clear_process_cache() -> None:
    _PROCESS_CACHE["fingerprint"] = None
    _PROCESS_CACHE["result"] = None


def _resolve_reference_years(df_ind: pd.DataFrame, df_aloc: pd.DataFrame) -> tuple[int | None, int | None]:
    years: set[int] = set()

    if not df_ind.empty and "ano" in df_ind.columns:
        years.update({int(y) for y in df_ind["ano"].dropna().tolist()})
    if not df_aloc.empty and "ano" in df_aloc.columns:
        years.update({int(y) for y in df_aloc["ano"].dropna().tolist()})

    if not years:
        return None, None

    ordered = sorted(years)
    current_year = ordered[-1]
    previous_year = ordered[-2] if len(ordered) >= 2 else None
    return current_year, previous_year


def _resolve_frame_years(df: pd.DataFrame) -> tuple[int | None, int | None]:
    if df.empty or "ano" not in df.columns:
        return None, None

    years = sorted({int(y) for y in df["ano"].dropna().tolist()})
    if not years:
        return None, None

    return years[-1], (years[-2] if len(years) >= 2 else None)


def _slice_by_year(df: pd.DataFrame, year: int | None, include_all_if_none: bool = False) -> pd.DataFrame:
    if df.empty:
        return df
    if year is None or "ano" not in df.columns:
        return df if include_all_if_none else pd.DataFrame(columns=df.columns)
    return df[df["ano"] == year]


def _compute_year_comparison(
    df_ind: pd.DataFrame,
    df_aloc: pd.DataFrame,
    current_year: int,
    previous_year: int,
) -> dict[str, Any]:
    if df_ind.empty and df_aloc.empty:
        return {
            "current_year": current_year,
            "previous_year": previous_year,
            "metrics": {},
        }

    cur = _build_people_snapshot(_slice_by_year(df_ind, current_year))
    prev = _build_people_snapshot(_slice_by_year(df_ind, previous_year))
    cur_aloc = _slice_by_year(df_aloc, current_year)
    prev_aloc = _slice_by_year(df_aloc, previous_year)

    def count_role(frame: pd.DataFrame, role_name: str) -> int:
        if frame.empty or "funcao" not in frame.columns:
            return 0
        return int((frame["funcao"] == role_name).sum())

    def with_delta(current: int, old: int) -> dict[str, Any]:
        delta = current - old
        delta_pct = round((delta / old) * 100, 2) if old else None
        return {
            "current": current,
            "previous": old,
            "delta": delta,
            "delta_pct": delta_pct,
        }

    cur_alocados = int(cur_aloc["alocados"].sum()) if not cur_aloc.empty and "alocados" in cur_aloc.columns else 0
    prev_alocados = int(prev_aloc["alocados"].sum()) if not prev_aloc.empty and "alocados" in prev_aloc.columns else 0
    cur_previstos = int(cur_aloc["previstos"].sum()) if not cur_aloc.empty and "previstos" in cur_aloc.columns else 0
    prev_previstos = int(prev_aloc["previstos"].sum()) if not prev_aloc.empty and "previstos" in prev_aloc.columns else 0

    metrics = {
        "total_indicados": with_delta(len(cur), len(prev)),
        "coordenador_estadual": with_delta(count_role(cur, "Coordenador Estadual"), count_role(prev, "Coordenador Estadual")),
        "coordenador_municipal": with_delta(count_role(cur, "Coordenador Municipal"), count_role(prev, "Coordenador Municipal")),
        "assistente": with_delta(count_role(cur, "Assistente"), count_role(prev, "Assistente")),
        "assistente_coordenador_estadual": with_delta(
            count_role(cur, "Assistente de Coordenador Estadual"),
            count_role(prev, "Assistente de Coordenador Estadual"),
        ),
        "assistente_coordenador_municipal": with_delta(
            count_role(cur, "Assistente de Coordenador Municipal"),
            count_role(prev, "Assistente de Coordenador Municipal"),
        ),
        "alocados": with_delta(cur_alocados, prev_alocados),
        "previstos": with_delta(cur_previstos, prev_previstos),
    }

    return {
        "current_year": current_year,
        "previous_year": previous_year,
        "metrics": metrics,
    }


def _build_all_collaborators(df_ind_current: pd.DataFrame, df_ind_all: pd.DataFrame, current_year: int, previous_year: int) -> list[dict[str, Any]]:
    """
    Consolida dados de todos os colaboradores para consulta individual.
    Versão otimizada usando pandas groupby.
    """
    if df_ind_all.empty:
        return []
    
    # Preparar dados do ano atual
    current_data = (
        df_ind_current[["nome", "CPF", "uf", "cidade", "funcao", "Escolaridade", "experiencia", "Capacitado", "indicado_em"]]
        .copy()
        if not df_ind_current.empty
        else pd.DataFrame()
    )
    
    # Preparar dados do ano anterior
    previous_data = df_ind_all[df_ind_all.get("ano", current_year) == previous_year].copy() if "ano" in df_ind_all.columns else pd.DataFrame()
    if not previous_data.empty:
        previous_data = previous_data[["nome", "CPF", "uf", "cidade", "funcao", "Escolaridade", "experiencia", "Capacitado", "indicado_em"]].copy()
    
    if not current_data.empty and "CPF" in current_data.columns:
        current_data["cpf_norm"] = current_data["CPF"].map(_normalize_cpf_digits)
    if not previous_data.empty and "CPF" in previous_data.columns:
        previous_data["cpf_norm"] = previous_data["CPF"].map(_normalize_cpf_digits)

    # Consolidar CPFs únicos
    all_cpfs = set()
    if not current_data.empty and "cpf_norm" in current_data.columns:
        all_cpfs.update(current_data["cpf_norm"].dropna().tolist())
    if not previous_data.empty and "cpf_norm" in previous_data.columns:
        all_cpfs.update(previous_data["cpf_norm"].dropna().tolist())
    
    collaborators: list[dict[str, Any]] = []
    
    for cpf in sorted(all_cpfs):
        cpf_str = _normalize_cpf_digits(cpf)
        if not cpf_str:
            continue
        
        # Encontrar dados do ano atual
        curr_rows = current_data[current_data["cpf_norm"] == cpf_str] if not current_data.empty else pd.DataFrame()
        
        # Encontrar dados do ano anterior
        prev_rows = previous_data[previous_data["cpf_norm"] == cpf_str] if not previous_data.empty else pd.DataFrame()
        
        # Usar primeiro registro disponível
        curr = curr_rows.iloc[0] if not curr_rows.empty else None
        prev = prev_rows.iloc[0] if not prev_rows.empty else None
        
        # Se não há nenhum dado, pular
        if curr is None and prev is None:
            continue
        
        # Montar informações do colaborador
        collaborator = {
            "nome": str(curr.get("nome", "") if curr is not None else prev.get("nome", "")).strip(),
            "cpf": cpf_str,
            "cpf_formatado": f"{cpf_str[:3]}.{cpf_str[3:6]}.{cpf_str[6:9]}-{cpf_str[9:]}" if len(cpf_str) == 11 else cpf_str,
            "uf": str(curr.get("uf", "") if curr is not None else prev.get("uf", "")).strip(),
            "cidade": str(curr.get("cidade", "") if curr is not None else prev.get("cidade", "")).strip(),
            
            # 2026
            "funcao_2026": str(curr.get("funcao", "")).strip() if curr is not None and pd.notna(curr.get("funcao")) else "",
            "escolaridade_2026": str(curr.get("Escolaridade", "")).strip() if curr is not None and pd.notna(curr.get("Escolaridade")) else "",
            "experiencia_2026": str(curr.get("experiencia", "")).strip() if curr is not None and pd.notna(curr.get("experiencia")) else "",
            "capacitado_2026": "Sim" if (curr is not None and _is_trained(curr.get("Capacitado"))) else "Não",
            "indicado_em_2026": str(curr.get("indicado_em", "")).strip() if curr is not None and pd.notna(curr.get("indicado_em")) else "",
            
            # 2025
            "funcao_2025": str(prev.get("funcao", "")).strip() if prev is not None and pd.notna(prev.get("funcao")) else "",
            "escolaridade_2025": str(prev.get("Escolaridade", "")).strip() if prev is not None and pd.notna(prev.get("Escolaridade")) else "",
            "experiencia_2025": str(prev.get("experiencia", "")).strip() if prev is not None and pd.notna(prev.get("experiencia")) else "",
            "capacitado_2025": "Sim" if (prev is not None and _is_trained(prev.get("Capacitado"))) else "Não",
            "indicado_em_2025": str(prev.get("indicado_em", "")).strip() if prev is not None and pd.notna(prev.get("indicado_em")) else "",
            
            # Status
            "status": "",
            "tipo": "",
        }
        
        # Determinar tipo
        if "Coordenador" in collaborator["funcao_2026"]:
            collaborator["tipo"] = "Coordenador"
        elif "Assistente" in collaborator["funcao_2026"]:
            collaborator["tipo"] = "Assistente"
        elif "Coordenador" in collaborator["funcao_2025"]:
            collaborator["tipo"] = "Coordenador"
        elif "Assistente" in collaborator["funcao_2025"]:
            collaborator["tipo"] = "Assistente"
        else:
            collaborator["tipo"] = "Outro"
        
        # Determinar status
        if curr is not None and prev is None:
            collaborator["status"] = "Novo"
        elif curr is None and prev is not None:
            collaborator["status"] = "Saiu"
        elif curr is not None and prev is not None:
            if collaborator["funcao_2026"] != collaborator["funcao_2025"]:
                collaborator["status"] = "Mudou de Função"
            else:
                collaborator["status"] = "Permanece"
        else:
            collaborator["status"] = "Inativo"
        
        collaborators.append(collaborator)
    
    return collaborators


def process_workspace_reports(reports_dir: Path | None = None) -> ProcessResult:
    base_dir = Path(__file__).resolve().parents[2]
    target_dir = reports_dir or (base_dir / "Relatórios")

    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError(f"Pasta de relatórios não encontrada: {target_dir}")

    file_paths = _find_report_files(target_dir)
    if not file_paths:
        raise FileNotFoundError(f"Nenhum arquivo Excel/CSV encontrado em: {target_dir}")

    fingerprint = _build_fingerprint(file_paths)
    if _PROCESS_CACHE["fingerprint"] == fingerprint and _PROCESS_CACHE["result"] is not None:
        return deepcopy(_PROCESS_CACHE["result"])

    alocacao_frames, indicados_frames = _split_files(file_paths)

    df_aloc = pd.concat(alocacao_frames, ignore_index=True) if alocacao_frames else pd.DataFrame()
    df_ind = pd.concat(indicados_frames, ignore_index=True) if indicados_frames else pd.DataFrame()

    df_aloc = _deduplicate_rows(df_aloc)
    df_ind = _deduplicate_rows(df_ind)

    current_year = datetime.now().year
    for frame in (df_ind, df_aloc):
        if frame.empty or "ano" not in frame.columns:
            continue

        valid_years = set(pd.to_numeric(frame["ano"], errors="coerce").dropna().astype(int).unique())
        if valid_years and valid_years == {current_year - 1}:
            frame["ano"] = current_year

    reference_year = current_year
    previous_year = reference_year - 1
    aloc_current_year = reference_year
    aloc_previous_year = previous_year

    df_ind_view = _slice_by_year(df_ind, reference_year)
    df_aloc_view = _slice_by_year(df_aloc, aloc_current_year, include_all_if_none=True)

    coord_filter = {"Coordenador Estadual", "Coordenador Municipal"}
    assistant_filter = {"Assistente", "Assistente de Coordenador Estadual", "Assistente de Coordenador Municipal"}

    # Coordenadores são indicados, não alocados
    coord_ind = (
        df_ind_view[df_ind_view["funcao"].isin(coord_filter)]
        if not df_ind_view.empty and "funcao" in df_ind_view.columns
        else pd.DataFrame(columns=["funcao"])
    )

    total_estadual = int(len(coord_ind[coord_ind["funcao"] == "Coordenador Estadual"])) if not coord_ind.empty else 0
    total_municipal = int(len(coord_ind[coord_ind["funcao"] == "Coordenador Municipal"])) if not coord_ind.empty else 0
    total_assistentes = int(df_ind_view["funcao"].isin(assistant_filter).sum()) if not df_ind_view.empty and "funcao" in df_ind_view.columns else 0
    assistente_estadual = int((df_ind_view["funcao"] == "Assistente de Coordenador Estadual").sum()) if not df_ind_view.empty and "funcao" in df_ind_view.columns else 0
    assistente_municipal = int((df_ind_view["funcao"] == "Assistente de Coordenador Municipal").sum()) if not df_ind_view.empty and "funcao" in df_ind_view.columns else 0

    veteran_count = int(df_ind_view["is_veteran"].sum()) if not df_ind_view.empty and "is_veteran" in df_ind_view.columns else 0
    total_indicados = int(len(df_ind_view))

    substitution_log = _build_substitution_log(df_ind_view)
    municipality_gaps, municipality_base_by_uf, coordinator_by_city, municipality_gap_summary = _build_municipality_coverage(
        df_ind_view,
        target_dir,
        aloc_current_year,
    )
    municipalities_without_coordinator = _build_municipalities_without_coordinator(df_ind_view, target_dir)
    returning_municipals, role_changes = _build_year_transition_views(df_ind, reference_year, previous_year)
    requirements_issues, requirements_metrics = _build_requirements_audit(df_ind_view)
    all_collaborators = _build_all_collaborators(df_ind_view, df_ind, reference_year, previous_year)

    if not df_aloc_view.empty and {"uf", "cidade"}.issubset(df_aloc_view.columns):
        alloc_map = (
            df_aloc_view.groupby(["uf", "cidade"], as_index=False)[["previstos", "alocados"]]
            .sum()
            .sort_values(["uf", "cidade"])
        )
        alloc_map_records = alloc_map.to_dict("records")
    else:
        alloc_map_records = []

    if not df_aloc_view.empty and "uf" in df_aloc_view.columns:
        by_uf = (
            df_aloc_view.groupby("uf", as_index=False)[["previstos", "alocados", "deficit"]]
            .sum()
            .sort_values("alocados", ascending=False)
        )
        by_uf_records = by_uf.to_dict("records")
    else:
        by_uf_records = []

    if not df_aloc_view.empty and "funcao" in df_aloc_view.columns:
        totals_role = (
            df_aloc_view.groupby("funcao", as_index=False)[["previstos", "alocados", "deficit"]]
            .sum()
            .sort_values("alocados", ascending=False)
            .to_dict("records")
        )
    else:
        totals_role = []

    # Contar coordenadores por UF para o mapa
    if not coord_ind.empty and "uf" in coord_ind.columns:
        coord_by_uf = (
            coord_ind.groupby("uf", as_index=False).size()
            .rename(columns={"size": "coordenadores"})
            .sort_values("coordenadores", ascending=False)
        )
        coord_by_uf_records = coord_by_uf.to_dict("records")
    else:
        coord_by_uf_records = []

    metrics = {
        "total_coordenador_estadual": total_estadual,
        "total_coordenador_municipal": total_municipal,
        "total_coordenadores": total_estadual + total_municipal,
        "total_assistentes": total_assistentes,
        "total_assistente_estadual": assistente_estadual,
        "total_assistente_municipal": assistente_municipal,
        "total_indicados": total_indicados,
        "current_year": reference_year,
        "previous_year": previous_year,
        "current_year_alocacao": aloc_current_year or reference_year,
        "previous_year_alocacao": aloc_previous_year or previous_year,
        "veteranos": veteran_count,
        "percentual_veteranos": round((veteran_count / total_indicados * 100), 2) if total_indicados else 0,
        "substituicoes": len(substitution_log),
        "municipios_base_alocacao": municipality_gap_summary["total_reference_cities"],
        "municipios_com_coordenador": municipality_gap_summary["covered_cities"],
        "municipios_sem_coordenador": len(
            {
                (row["uf"], city.strip())
                for row in municipality_gaps
                for city in str(row.get("municipios", "")).split(",")
                if city.strip()
            }
        ),
        "ano_base_cobertura_municipal": municipality_gap_summary["reference_year"],
        "municipais_atuaram_2025_2026": len(returning_municipals),
        "mudaram_funcao_2025_2026": len(role_changes),
        "year_comparison": _compute_year_comparison(
            df_ind,
            df_aloc,
            current_year=reference_year,
            previous_year=previous_year,
        ),
    }
    metrics.update(requirements_metrics)

    charts = {
        "allocation_by_uf": by_uf_records,
        "allocation_by_city": alloc_map_records,
        "coordinator_by_uf": coord_by_uf_records,
        "coordinator_distribution": [
            {"funcao": "Coordenador Estadual", "indicados": total_estadual},
            {"funcao": "Coordenador Municipal", "indicados": total_municipal},
            {"funcao": "Assistente Estadual", "indicados": assistente_estadual},
            {"funcao": "Assistente Municipal", "indicados": assistente_municipal},
        ],
    }

    result = ProcessResult(
        metrics=metrics,
        charts=charts,
        substitution_log=substitution_log,
        totals_by_role=totals_role,
        municipality_gaps=municipality_gaps,
        municipality_base_by_uf=municipality_base_by_uf,
        coordinator_by_city=coordinator_by_city,
        returning_municipals=returning_municipals,
        role_changes=role_changes,
        requirements_issues=requirements_issues,
        municipalities_without_coordinator=municipalities_without_coordinator,
        all_collaborators=all_collaborators,
    )

    _PROCESS_CACHE["fingerprint"] = fingerprint
    _PROCESS_CACHE["result"] = deepcopy(result)
    return result
