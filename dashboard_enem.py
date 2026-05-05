from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.app.processor import clear_process_cache, process_workspace_reports


BASE_DIR = Path(__file__).resolve().parent
RELATORIOS_DIR = BASE_DIR / "Relatórios"
GEOJSON_PATH = BASE_DIR / "frontend" / "src" / "data" / "brazil-states.geojson"
LOGO_PATH = BASE_DIR / "cebraspe_logo.jpg"

CEB_NAVY_900 = "#060C30"
CEB_NAVY_700 = "#1F2F63"
CEB_BLUE_500 = "#0C4A87"
CEB_BLUE_300 = "#4875BD"
CEB_ORANGE_500 = "#F26716"
CEB_ORANGE_300 = "#FA7D23"
CEB_BG = "#f4f7fc"
CEB_SAND = "#F7F1E8"
CEB_TEXT = "#15213D"


def _reports_signature() -> tuple[tuple[str, int, int, str], ...]:
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha1()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    if not RELATORIOS_DIR.exists():
        return tuple()

    rows: list[tuple[str, int, int, str]] = []
    for file_path in sorted(RELATORIOS_DIR.iterdir()):
        if not file_path.is_file() or file_path.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
            continue
        stat = file_path.stat()
        rows.append((file_path.name, int(stat.st_mtime_ns), int(stat.st_size), _file_hash(file_path)))
    processor_stat = Path(process_workspace_reports.__code__.co_filename).stat()
    processor_path = Path(process_workspace_reports.__code__.co_filename)
    rows.append(("__processor__", int(processor_stat.st_mtime_ns), int(processor_stat.st_size), _file_hash(processor_path)))
    return tuple(rows)


@st.cache_data(show_spinner=False)
def _load_dashboard_data(signature: tuple[tuple[str, int, int, str], ...]) -> dict[str, Any]:
    _ = signature
    result = process_workspace_reports()
    return {
        "metrics": result.metrics,
        "charts": result.charts,
        "substitution_log": result.substitution_log,
        "totals_by_role": result.totals_by_role,
        "municipality_gaps": result.municipality_gaps,
        "municipality_base_by_uf": result.municipality_base_by_uf,
        "coordinator_by_city": result.coordinator_by_city,
        "returning_municipals": result.returning_municipals,
        "role_changes": result.role_changes,
        "requirements_issues": result.requirements_issues,
        "municipalities_without_coordinator": result.municipalities_without_coordinator,
        "all_collaborators": result.all_collaborators,
    }


def _comparison_rows(year_metrics: dict[str, Any]) -> pd.DataFrame:
    labels = {
        "total_indicados": "Total Indicados",
        "coordenador_estadual": "Coordenador Estadual",
        "coordenador_municipal": "Coordenador Municipal",
        "assistente_coordenador_estadual": "Assistente Coord. Estadual",
        "assistente_coordenador_municipal": "Assistente Coord. Municipal",
    }
    rows: list[dict[str, Any]] = []
    for key, label in labels.items():
        entry = year_metrics.get(key, {})
        delta = entry.get("delta")
        delta_fmt = "-" if delta is None else (f"+{delta}" if delta > 0 else str(delta))
        rows.append(
            {
                "Indicador": label,
                "Atual": entry.get("current", "-"),
                "Anterior": entry.get("previous", "-"),
                "Delta": delta_fmt,
                "Delta %": "-" if entry.get("delta_pct") is None else f"{float(entry['delta_pct']):+.2f}%".replace(".", ","),
            }
        )
    return pd.DataFrame(rows)


def _stat_list(rows: list[dict[str, Any]], key: str, label: str) -> pd.DataFrame:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key, "")).strip() or "Sem informacao"
        counts[value] = counts.get(value, 0) + 1
    sorted_rows = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return pd.DataFrame([{label: name, "Quantidade": count} for name, count in sorted_rows])


def _metric_snapshot(metric_map: dict[str, Any], key: str) -> tuple[int, int, int | None, float | None]:
    entry = metric_map.get(key, {})
    current = int(entry.get("current", 0) or 0)
    previous = int(entry.get("previous", 0) or 0)
    delta = entry.get("delta")
    delta_pct = entry.get("delta_pct")
    return current, previous, delta, delta_pct


def _format_delta(delta: int | float | None, delta_pct: float | None = None, suffix: str = "") -> str:
    if delta is None:
        return "-"

    delta_value = f"{delta:+}"
    if suffix:
        delta_value = f"{delta_value}{suffix}"

    if delta_pct is None:
        return delta_value

    pct_value = f"{delta_pct:+.2f}%".replace(".", ",")
    return f"{delta_value} ({pct_value})"


def _format_ratio(current: float, previous: float) -> str:
    delta = current - previous
    return f"{delta:+.2f} p.p.".replace(".", ",")


def _sanitize_cell_for_streamlit(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False)
    if pd.isna(value):
        return None
    return value


def _format_cpf(cpf: str) -> str:
    """Formata CPF para o padrão 000.000.000-00."""
    if not cpf:
        return ""

    cpf_clean = re.sub(r"\D", "", str(cpf))
    if not cpf_clean:
        return ""

    if len(cpf_clean) < 11:
        cpf_clean = cpf_clean.zfill(11)
    elif len(cpf_clean) > 11:
        cpf_clean = cpf_clean[:11]

    return f"{cpf_clean[:3]}.{cpf_clean[3:6]}.{cpf_clean[6:9]}-{cpf_clean[9:]}"


def _normalize_cpf_display(cpf: Any) -> str:
    cpf_clean = re.sub(r"\D", "", str(cpf or ""))
    return cpf_clean.zfill(11)[:11] if cpf_clean else ""


def _sanitize_dataframe_for_streamlit(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sanitized = df.copy()
    sanitized.columns = [str(column) for column in sanitized.columns]
    for column in sanitized.columns:
        sanitized[column] = sanitized[column].map(_sanitize_cell_for_streamlit)
    return sanitized


def _build_compare_chart(year_metrics: dict[str, Any], current_year: int, previous_year: int) -> pd.DataFrame:
    labels = {
        "coordenador_estadual": "Coord. Estadual",
        "coordenador_municipal": "Coord. Municipal",
        "assistente_coordenador_estadual": "Assist. Estadual",
        "assistente_coordenador_municipal": "Assist. Municipal",
        "total_indicados": "Total Indicados",
    }
    rows: list[dict[str, Any]] = []

    for key, label in labels.items():
        current, previous, _, _ = _metric_snapshot(year_metrics, key)
        rows.append({"Indicador": label, "Ano": str(previous_year), "Quantidade": previous})
        rows.append({"Indicador": label, "Ano": str(current_year), "Quantidade": current})

    return pd.DataFrame(rows)


def _apply_figure_theme(fig: Any) -> Any:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.88)",
        font={"family": "Bahnschrift, Segoe UI, sans-serif", "color": CEB_TEXT},
        title_font={"size": 20, "color": CEB_NAVY_900},
        legend_title_text="",
        margin={"l": 16, "r": 16, "t": 64, "b": 16},
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(31,47,99,0.10)", zeroline=False)
    return fig


def _render_command_panel(current_year: int) -> None:
    st.markdown(
        f"""
        <div class="command-panel">
          <div>
            <span class="eyebrow">CENTRAL LOGISTICA</span>
            <h3>Edicao ENEM {current_year}</h3>
            <p>Painel executivo com leitura automatica, comparativo historico e monitoramento de substituicoes.</p>
          </div>
          <div class="command-badge">Atualizacao sob demanda</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_section_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="section-heading">
          <span class="eyebrow">{title}</span>
          <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_map(coordinator_by_uf: list[dict[str, Any]]) -> None:
    if not coordinator_by_uf:
        st.info("Sem dados de coordenadores por UF para renderizar mapa.")
        return

    map_df = pd.DataFrame(coordinator_by_uf)
    if map_df.empty:
        st.info("Sem dados de coordenadores por UF para renderizar mapa.")
        return

    if GEOJSON_PATH.exists():
        geojson = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))
        fig = px.choropleth(
            map_df,
            geojson=geojson,
            locations="uf",
            color="coordenadores",
            featureidkey="properties.sigla",
            color_continuous_scale=[CEB_BLUE_300, CEB_BLUE_500, CEB_NAVY_700],
            projection="mercator",
            title="Coordenadores Indicados por UF",
        )
        fig.update_geos(fitbounds="locations", visible=False)
        fig.update_layout(margin={"r": 0, "t": 40, "l": 0, "b": 0})
        _apply_figure_theme(fig)
        st.plotly_chart(fig, width="stretch")
    else:
        fig = px.bar(map_df, x="uf", y="coordenadores", title="Coordenadores Indicados por UF")
        _apply_figure_theme(fig)
        st.plotly_chart(fig, width="stretch")


def _inject_cebraspe_theme() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{
            background:
                radial-gradient(circle at top left, rgba(250,125,35,0.12), transparent 22%),
                radial-gradient(circle at top right, rgba(72,117,189,0.18), transparent 28%),
                linear-gradient(180deg, #eef3fb 0%, {CEB_BG} 46%, #edf2f9 100%);
            color: {CEB_TEXT};
            font-family: Bahnschrift, "Segoe UI", sans-serif;
        }}
        .block-container {{
            padding-top: 1.6rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }}
        h1, h2, h3, h4 {{
            letter-spacing: -0.02em;
        }}
        .cebraspe-hero {{
            background:
                radial-gradient(circle at 80% 20%, rgba(255,255,255,0.18), transparent 18%),
                linear-gradient(130deg, {CEB_NAVY_900}, {CEB_NAVY_700} 54%, {CEB_BLUE_500});
            color: white;
            border-radius: 24px;
            padding: 26px 28px;
            margin-bottom: 18px;
            border: 1px solid rgba(255,255,255,0.16);
            box-shadow: 0 24px 50px rgba(6,12,48,0.24);
            position: relative;
            overflow: hidden;
        }}
        .cebraspe-hero h1 {{
            margin: 0;
            font-size: 2.3rem;
            font-weight: 900;
        }}
        .cebraspe-hero p {{
            margin: 10px 0 0;
            opacity: 0.92;
            max-width: 760px;
            line-height: 1.45;
        }}
        .hero-chip-row {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 16px;
        }}
        .hero-chip {{
            background: rgba(255,255,255,0.10);
            border: 1px solid rgba(255,255,255,0.18);
            border-radius: 999px;
            padding: 6px 12px;
            font-size: 0.84rem;
            font-weight: 700;
            letter-spacing: 0.03em;
        }}
        .command-panel {{
            display: flex;
            justify-content: space-between;
            align-items: end;
            gap: 16px;
            background: rgba(255,255,255,0.72);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(31,47,99,0.08);
            border-radius: 20px;
            padding: 16px 18px;
            margin: 0.4rem 0 1rem 0;
            box-shadow: 0 12px 32px rgba(6,12,48,0.08);
        }}
        .command-panel h3 {{
            margin: 6px 0 4px;
            color: {CEB_NAVY_900};
            font-size: 1.2rem;
        }}
        .command-panel p {{
            margin: 0;
            color: #53617e;
        }}
        .command-badge {{
            background: linear-gradient(135deg, {CEB_SAND}, #fff);
            color: {CEB_NAVY_900};
            border: 1px solid rgba(242,103,22,0.22);
            border-radius: 16px;
            padding: 0.8rem 1rem;
            font-weight: 800;
            white-space: nowrap;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.6);
        }}
        .eyebrow {{
            display: inline-block;
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            color: {CEB_ORANGE_500};
        }}
        .highlight-strip {{
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 14px;
            margin: 0.6rem 0 1.15rem 0;
        }}
        .highlight-card {{
            background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(255,255,255,0.82));
            border: 1px solid rgba(31,47,99,0.08);
            border-radius: 18px;
            padding: 16px 16px 14px;
            min-height: 112px;
            box-shadow: 0 18px 30px rgba(6,12,48,0.06);
            position: relative;
            overflow: hidden;
        }}
        .highlight-card::before {{
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: 100%;
            height: 4px;
            background: linear-gradient(90deg, {CEB_ORANGE_500}, {CEB_BLUE_300});
        }}
        .highlight-card span {{
            display: block;
            color: #62708c;
            font-size: 0.82rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }}
        .highlight-card strong {{
            display: block;
            margin-top: 10px;
            color: {CEB_NAVY_900};
            font-size: 1.8rem;
            font-weight: 900;
        }}
        .highlight-card small {{
            display: block;
            margin-top: 8px;
            color: #62708c;
            line-height: 1.35;
        }}
        .section-heading {{
            margin: 0.2rem 0 0.8rem 0;
        }}
        .section-heading p {{
            margin: 0.2rem 0 0;
            color: #61708d;
            font-size: 0.96rem;
        }}
        div[data-testid="stMetric"] {{
            background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(255,255,255,0.88));
            border: 1px solid rgba(31,47,99,0.08);
            border-radius: 18px;
            padding: 12px 14px;
            box-shadow: 0 14px 24px rgba(12,74,135,0.08);
            position: relative;
            overflow: hidden;
        }}
        div[data-testid="stMetric"]::before {{
            content: "";
            position: absolute;
            inset: 0 auto auto 0;
            width: 100%;
            height: 3px;
            background: linear-gradient(90deg, {CEB_BLUE_500}, {CEB_ORANGE_500});
        }}
        label[data-testid="stMetricLabel"] {{
            color: #5d6c88 !important;
            font-weight: 800;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            font-size: 0.75rem;
        }}
        div[data-testid="stMetricValue"] {{
            color: {CEB_NAVY_900};
            font-weight: 900;
        }}
        div[data-testid="stMetricDelta"] {{
            font-weight: 700;
        }}
        .stButton > button {{
            background: linear-gradient(135deg, {CEB_ORANGE_500}, {CEB_ORANGE_300});
            color: white;
            border: none;
            border-radius: 24px;
            font-weight: 800;
            padding: 1.15rem 1.4rem;
            min-height: 6.1rem;
            font-size: 1.08rem;
            line-height: 1.3;
            white-space: normal;
            text-align: center;
            box-shadow: 0 12px 22px rgba(242,103,22,0.24);
        }}
        .stButton > button:hover {{
            background: linear-gradient(135deg, {CEB_ORANGE_300}, #ff9b56);
            color: white;
            transform: translateY(-1px);
        }}
        .stTabs [data-baseweb="tab-list"] {{
            gap: 10px;
            background: rgba(255,255,255,0.62);
            padding: 8px;
            border-radius: 18px;
            border: 1px solid rgba(31,47,99,0.08);
        }}
        .stTabs [data-baseweb="tab"] {{
            background: transparent;
            border-radius: 12px;
            border: 1px solid transparent;
            color: {CEB_NAVY_700};
            font-weight: 700;
            padding: 0.65rem 1rem;
        }}
        .stTabs [aria-selected="true"] {{
            background: linear-gradient(135deg, {CEB_BLUE_500}, {CEB_BLUE_300});
            color: white;
            border-color: rgba(255,255,255,0.15);
            box-shadow: 0 12px 22px rgba(12,74,135,0.22);
        }}
        div[data-testid="stPlotlyChart"],
        div[data-testid="stDataFrame"] {{
            background: rgba(255,255,255,0.82);
            border: 1px solid rgba(31,47,99,0.08);
            border-radius: 22px;
            padding: 10px;
            box-shadow: 0 18px 36px rgba(6,12,48,0.06);
        }}
        div[data-testid="stCaptionContainer"] p {{
            color: #60708c;
        }}
        @media (max-width: 1100px) {{
            .highlight-strip {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
            .command-panel {{
                flex-direction: column;
                align-items: start;
            }}
        }}
        @media (max-width: 640px) {{
            .highlight-strip {{
                grid-template-columns: 1fr;
            }}
            .cebraspe-hero {{
                padding: 22px 20px;
            }}
            .cebraspe-hero h1 {{
                font-size: 1.9rem;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_hero() -> None:
    col_logo, col_text = st.columns([1, 8])
    with col_logo:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=88)
    with col_text:
        st.markdown(
            """
            <div class="cebraspe-hero">
              <h1>Dashboard ENEM</h1>
              <p>Dashboard de acompanhamento de pessoal ENEM 2026</p>
              <div class="hero-chip-row">
                <span class="hero-chip">Painel Logistico</span>
                <span class="hero-chip">Comparativo Anual</span>
                <span class="hero-chip">Leitura Automatizada</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def main() -> None:
    st.set_page_config(page_title="Dashboard ENEM", layout="wide", page_icon="📊")
    _inject_cebraspe_theme()
    _render_hero()

    st.caption("Aba principal com metricas somente da edicao atual e comparativo anual em aba dedicada.")

    signature = _reports_signature()
    if not signature:
        st.error("Nenhum arquivo Excel/CSV encontrado na pasta Relatorios.")
        return

    col_left, col_right = st.columns([1, 5])
    with col_left:
        refresh = st.button("Atualizar dados")
    with col_right:
        st.write("")

    if refresh:
        clear_process_cache()
        _load_dashboard_data.clear()
        st.rerun()

    with st.spinner("Processando planilhas..."):
        data = _load_dashboard_data(signature)

    metrics = data.get("metrics", {})
    charts = data.get("charts", {})
    substitution_log = data.get("substitution_log", [])
    totals_by_role = data.get("totals_by_role", [])
    municipality_gaps = data.get("municipality_gaps", [])
    municipality_base_by_uf = data.get("municipality_base_by_uf", [])
    coordinator_by_city = data.get("coordinator_by_city", [])
    returning_municipals = data.get("returning_municipals", [])
    role_changes = data.get("role_changes", [])
    requirements_issues = data.get("requirements_issues", [])
    municipalities_without_coordinator = data.get("municipalities_without_coordinator", [])
    all_collaborators = data.get("all_collaborators", [])

    year_cmp = metrics.get("year_comparison", {})
    cmp_metrics = year_cmp.get("metrics", {})
    coord_by_uf = pd.DataFrame(charts.get("coordinator_by_uf", []))

    if not coord_by_uf.empty:
        resumo_ufs = f"Coordenadores indicados por UF: {len(coord_by_uf)} UFs e {int(coord_by_uf['coordenadores'].sum())} coordenadores."
        st.markdown(
            f"<div style='margin: 0.2rem 0 0.8rem 0; color: #64748b; font-size: 0.92rem; line-height: 1.2;'>{resumo_ufs}</div>",
            unsafe_allow_html=True,
        )

    current_year = int(metrics.get("current_year") or datetime.now().year)
    previous_year = int(metrics.get("previous_year") or (current_year - 1))

    _render_command_panel(current_year)
    metric_col_1, metric_col_2, metric_col_3, metric_col_4 = st.columns(4)
    with metric_col_1:
        st.metric("Coordenadores Estaduais", int(metrics.get("total_coordenador_estadual", 0)))
    with metric_col_2:
        st.metric("Coordenadores Municipais", int(metrics.get("total_coordenador_municipal", 0)))
    with metric_col_3:
        st.metric("Assistentes Estaduais", int(metrics.get("total_assistente_estadual", 0)))
    with metric_col_4:
        st.metric("Assistentes Municipais", int(metrics.get("total_assistente_municipal", 0)))

    tab_overview, tab_compare, tab_requirements, tab_municSemCoord, tab_collaborators, tab_subs, tab_map = st.tabs(
        [
            f"Visao Geral {current_year}",
            f"Comparativo {current_year} x {previous_year}",
            "Cobertura e Requisitos",
            "Municipios sem Coordenador",
            "Consulta de Colaborador",
            "Substituidos",
            "Mapa Brasil",
        ]
    )

    with tab_overview:
        _render_section_header("Visao Geral", "Panorama da etapa atual com distribuicao operacional e leitura rapida por funcao.")
        
        col_select, col_details = st.columns([1, 2])
        
        with col_select:
            st.subheader("Filtro por Estado")
            if not coord_by_uf.empty:
                lista_ufs = sorted(coord_by_uf["uf"].unique())
                uf_selecionada = st.selectbox("Selecione uma UF para detalhamento:", lista_ufs)
                
                # Dados da UF selecionada
                dados_uf = coord_by_uf[coord_by_uf["uf"] == uf_selecionada].iloc[0]
                total_coord_uf = int(dados_uf["coordenadores"])
                
                st.markdown(f"""
                    <div style="background: {CEB_BLUE_500}; color: white; padding: 25px; border-radius: 20px; text-align: center; margin-top: 15px; box-shadow: 0 10px 25px rgba(6,12,48,0.15);">
                        <p style="margin:0; font-size: 1.1rem; opacity: 0.85; text-transform: uppercase; letter-spacing: 0.1em;">Total em {uf_selecionada}</p>
                        <h1 style="margin:5px 0; font-size: 4rem; font-weight: 900;">{total_coord_uf}</h1>
                        <p style="margin:0; font-weight: bold;">Coordenadores Indicados</p>
                    </div>
                """, unsafe_allow_html=True)
            else:
                st.info("Sem dados de UFs disponíveis.")

        with col_details:
            st.subheader("Perfil de Indicados 2026")
            coord_dist = pd.DataFrame(charts.get("coordinator_distribution", []))
            if not coord_dist.empty:
                fig = px.pie(
                    coord_dist,
                    values="indicados",
                    names="funcao",
                    hole=0.6,
                    title="Distribuicao por Funcao (Geral)",
                    color_discrete_sequence=[CEB_BLUE_500, CEB_ORANGE_500, CEB_BLUE_300, CEB_ORANGE_300]
                )
                _apply_figure_theme(fig)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem dados de distribuicao.")

        st.markdown("---")
        st.subheader("Ranking de Coordenadores por UF (Top 10)")
        if not coord_by_uf.empty:
            top_10_uf = coord_by_uf.head(10).copy()
            top_10_uf.columns = ["Estado (UF)", "Total de Coordenadores Indicados"]
            st.dataframe(_sanitize_dataframe_for_streamlit(top_10_uf), width="stretch", hide_index=True)
        else:
            st.info("Resumo de UFs indisponível.")

    with tab_compare:
        _render_section_header(
            f"Comparativo {current_year} x {previous_year}",
            "Leitura historica da etapa atual, comparando somente coordenacoes e assistencias ja indicadas.",
        )

        total_indicados_atual, total_indicados_anterior, delta_indicados, delta_pct_indicados = _metric_snapshot(
            cmp_metrics, "total_indicados"
        )
        coord_est_atual, coord_est_anterior, delta_coord_est, delta_pct_coord_est = _metric_snapshot(
            cmp_metrics, "coordenador_estadual"
        )
        coord_mun_atual, coord_mun_anterior, delta_coord_mun, delta_pct_coord_mun = _metric_snapshot(
            cmp_metrics, "coordenador_municipal"
        )
        assist_est_atual, assist_est_anterior, delta_assist_est, delta_pct_assist_est = _metric_snapshot(
            cmp_metrics, "assistente_coordenador_estadual"
        )
        assist_mun_atual, assist_mun_anterior, delta_assist_mun, delta_pct_assist_mun = _metric_snapshot(
            cmp_metrics, "assistente_coordenador_municipal"
        )

        total_coord_atual = coord_est_atual + coord_mun_atual
        total_coord_anterior = coord_est_anterior + coord_mun_anterior
        total_assist_atual = assist_est_atual + assist_mun_atual
        total_assist_anterior = assist_est_anterior + assist_mun_anterior
        participacao_coord_atual = (total_coord_atual / total_indicados_atual * 100) if total_indicados_atual else 0.0
        participacao_coord_anterior = (
            (total_coord_anterior / total_indicados_anterior * 100) if total_indicados_anterior else 0.0
        )
        participacao_assist_atual = (total_assist_atual / total_indicados_atual * 100) if total_indicados_atual else 0.0
        participacao_assist_anterior = (
            (total_assist_anterior / total_indicados_anterior * 100) if total_indicados_anterior else 0.0
        )
        razao_assist_por_coord_atual = (total_assist_atual / total_coord_atual) if total_coord_atual else 0.0
        razao_assist_por_coord_anterior = (total_assist_anterior / total_coord_anterior) if total_coord_anterior else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            f"Indicados {current_year}",
            total_indicados_atual,
            _format_delta(delta_indicados, delta_pct_indicados),
            border=True,
        )
        m2.metric(
            f"Coord. Estaduais {current_year}",
            coord_est_atual,
            _format_delta(delta_coord_est, delta_pct_coord_est),
            border=True,
        )
        m3.metric(
            f"Coord. Municipais {current_year}",
            coord_mun_atual,
            _format_delta(delta_coord_mun, delta_pct_coord_mun),
            border=True,
        )
        m4.metric(
            f"Assist. Estaduais {current_year}",
            assist_est_atual,
            _format_delta(delta_assist_est, delta_pct_assist_est),
            border=True,
        )

        m5, m6, m7, m8 = st.columns(4)
        m5.metric(
            f"Assist. Municipais {current_year}",
            assist_mun_atual,
            _format_delta(delta_assist_mun, delta_pct_assist_mun),
            border=True,
        )
        m6.metric(
            f"Total Coordenacoes {current_year}",
            total_coord_atual,
            f"{total_coord_atual - total_coord_anterior:+}",
            border=True,
        )
        m7.metric(
            f"Total Assistencias {current_year}",
            total_assist_atual,
            f"{total_assist_atual - total_assist_anterior:+}",
            border=True,
        )
        m8.metric(
            f"Participacao Coord. {current_year}",
            f"{participacao_coord_atual:.2f}%".replace(".", ","),
            _format_ratio(participacao_coord_atual, participacao_coord_anterior),
            border=True,
        )

        m9, m10, m11, m12 = st.columns(4)
        m9.metric(
            f"Participacao Assist. {current_year}",
            f"{participacao_assist_atual:.2f}%".replace(".", ","),
            _format_ratio(participacao_assist_atual, participacao_assist_anterior),
            border=True,
        )
        m10.metric(
            f"Assist./Coord. {current_year}",
            f"{razao_assist_por_coord_atual:.2f}".replace(".", ","),
            f"{(razao_assist_por_coord_atual - razao_assist_por_coord_anterior):+.2f}".replace(".", ","),
            border=True,
        )
        m11.metric(f"Base {previous_year}", total_indicados_anterior, border=True)
        m12.metric(
            f"Assist./Coord. {previous_year}",
            f"{razao_assist_por_coord_anterior:.2f}".replace(".", ","),
            border=True,
        )

        compare_chart_df = _build_compare_chart(cmp_metrics, current_year, previous_year)
        if not compare_chart_df.empty:
            fig = px.bar(
                compare_chart_df,
                x="Indicador",
                y="Quantidade",
                color="Ano",
                barmode="group",
                title=f"Comparativo operacional {current_year} x {previous_year}",
                color_discrete_sequence=[CEB_BLUE_300, CEB_ORANGE_500],
            )
            _apply_figure_theme(fig)
            st.plotly_chart(fig, width="stretch")

        resumo_compare = pd.DataFrame(
            [
                {
                    "Indicador": "Total de coordenacoes",
                    str(previous_year): total_coord_anterior,
                    str(current_year): total_coord_atual,
                    "Delta": f"{total_coord_atual - total_coord_anterior:+}",
                },
                {
                    "Indicador": "Total de assistencias",
                    str(previous_year): total_assist_anterior,
                    str(current_year): total_assist_atual,
                    "Delta": f"{total_assist_atual - total_assist_anterior:+}",
                },
                {
                    "Indicador": "Participacao de coordenacoes",
                    str(previous_year): f"{participacao_coord_anterior:.2f}%".replace(".", ","),
                    str(current_year): f"{participacao_coord_atual:.2f}%".replace(".", ","),
                    "Delta": _format_ratio(participacao_coord_atual, participacao_coord_anterior),
                },
                {
                    "Indicador": "Participacao de assistencias",
                    str(previous_year): f"{participacao_assist_anterior:.2f}%".replace(".", ","),
                    str(current_year): f"{participacao_assist_atual:.2f}%".replace(".", ","),
                    "Delta": _format_ratio(participacao_assist_atual, participacao_assist_anterior),
                },
                {
                    "Indicador": "Razao assistencias por coordenacao",
                    str(previous_year): f"{razao_assist_por_coord_anterior:.2f}".replace(".", ","),
                    str(current_year): f"{razao_assist_por_coord_atual:.2f}".replace(".", ","),
                    "Delta": f"{(razao_assist_por_coord_atual - razao_assist_por_coord_anterior):+.2f}".replace(".", ","),
                },
            ]
        )
        resumo_compare_display = resumo_compare.astype(str)
        st.dataframe(_sanitize_dataframe_for_streamlit(resumo_compare_display), width="stretch", hide_index=True)
        st.dataframe(_sanitize_dataframe_for_streamlit(_comparison_rows(cmp_metrics)), width="stretch", hide_index=True)

    with tab_requirements:
        _render_section_header(
            "Cobertura e Requisitos",
            "Leitura dos municipios sem coordenador municipal indicado, movimentacoes nominais 2025 x 2026 e aderencia aos pre-requisitos da TR.",
        )

        coverage_base_year = metrics.get("ano_base_cobertura_municipal")
        coverage_caption = "Base territorial de municipios comparada com coordenadores municipais indicados na edicao atual."
        if coverage_base_year:
            coverage_caption = (
                f"Base territorial de municipios considerada a partir da ultima alocacao disponivel ({coverage_base_year})."
            )
        st.caption(coverage_caption)

        gap_df = pd.DataFrame(municipality_gaps)
        base_by_uf_df = pd.DataFrame(municipality_base_by_uf)
        city_coord_df = pd.DataFrame(coordinator_by_city)
        returning_df = pd.DataFrame(returning_municipals)
        role_changes_df = pd.DataFrame(role_changes)
        requirements_df = pd.DataFrame(requirements_issues)
        formation_issues_df = requirements_df[requirements_df["formacao_ok"] == "Nao"].copy() if not requirements_df.empty else pd.DataFrame()
        experience_issues_df = requirements_df[requirements_df["experiencia_ok"] == "Nao"].copy() if not requirements_df.empty else pd.DataFrame()
        training_issues_df = requirements_df[requirements_df["capacitacao_ok"] == "Nao"].copy() if not requirements_df.empty else pd.DataFrame()

        coverage_cards = [
            {
                "id": "base",
                "title": "Municipios na base",
                "value": int(metrics.get("municipios_base_alocacao", 0)),
                "summary": "Base territorial utilizada para validar a cobertura municipal.",
                "detail": (
                    f"A base considera a ultima alocacao disponivel ({coverage_base_year})."
                    if coverage_base_year
                    else "Base territorial sem ano de referencia identificado."
                ),
                "table": base_by_uf_df,
                "empty_text": "Nao foi possivel consolidar a base de municipios por UF.",
            },
            {
                "id": "covered",
                "title": "Municipios cobertos",
                "value": int(metrics.get("municipios_com_coordenador", 0)),
                "summary": "Municipios com coordenador municipal indicado.",
                "detail": "Mostra os municipios da base atual que ja contam com coordenador municipal indicado.",
                "table": city_coord_df,
                "empty_text": "Sem consolidacao de coordenadores por municipio.",
            },
            {
                "id": "missing",
                "title": "Sem coord. municipal",
                "value": int(metrics.get("municipios_sem_coordenador", 0)),
                "summary": "Municipios da base ainda sem cobertura municipal.",
                "detail": "Lista os municipios que existem na base de referencia, mas ainda nao tem coordenador municipal indicado.",
                "table": gap_df,
                "empty_text": "Nenhum municipio sem coordenador municipal foi identificado.",
            },
            {
                "id": "returning",
                "title": "Municipais 2025 e 2026",
                "value": int(metrics.get("municipais_atuaram_2025_2026", 0)),
                "summary": "Municipais presentes nas duas edicoes.",
                "detail": f"Consolida os coordenadores municipais identificados em {previous_year} e {current_year}.",
                "table": returning_df,
                "empty_text": "Nenhum coordenador municipal foi encontrado nas duas edicoes.",
            },
            {
                "id": "role_changes",
                "title": "Mudaram de funcao",
                "value": int(metrics.get("mudaram_funcao_2025_2026", 0)),
                "summary": "Pessoas com troca de funcao entre as edicoes.",
                "detail": f"Lista as pessoas que mudaram de funcao entre {previous_year} e {current_year}.",
                "table": role_changes_df,
                "empty_text": "Nenhuma mudanca de funcao foi identificada.",
            },
            {
                "id": "formation",
                "title": "Sem formacao",
                "value": int(metrics.get("sem_formacao_necessaria", 0)),
                "summary": "Pessoas fora do requisito de escolaridade.",
                "detail": "A aderencia a formacao exige superior completo para as funcoes acompanhadas.",
                "table": formation_issues_df,
                "empty_text": "Nenhuma pendencia de formacao foi encontrada.",
            },
            {
                "id": "experience",
                "title": "Fora da experiencia",
                "value": int(metrics.get("fora_regra_experiencia", 0)),
                "summary": "Pessoas fora do minimo de experiencia.",
                "detail": "O card mostra os casos em que a experiencia informada nao atende ao minimo esperado para a funcao.",
                "table": experience_issues_df,
                "empty_text": "Nenhuma pendencia de experiencia foi encontrada.",
            },
            {
                "id": "training",
                "title": "Sem capacitacao",
                "value": int(metrics.get("sem_capacitacao", 0)),
                "summary": "Pessoas sem capacitacao valida.",
                "detail": "Exibe os registros sem capacitacao confirmada na base atual.",
                "table": training_issues_df,
                "empty_text": "Nenhuma pendencia de capacitacao foi encontrada.",
            },
        ]

        coverage_ids = {card["id"] for card in coverage_cards}
        if "coverage_focus" not in st.session_state or st.session_state["coverage_focus"] not in coverage_ids:
            st.session_state["coverage_focus"] = coverage_cards[0]["id"]

        st.caption("Clique em um card para ver os detalhes do indicador selecionado.")
        
        # Estilo para cards selecionados e interativos
        st.markdown("""
            <style>
            div[data-testid="stHorizontalBlock"] > div:has(button[key^="coverage_card_"]) {
                background: rgba(255,255,255,0.4);
                border-radius: 20px;
                padding: 10px;
                transition: all 0.3s ease;
            }
            /* Melhorando a aparência do botão como um card */
            .stButton > button[key^="coverage_card_"] {
                border-radius: 16px !important;
                height: auto !important;
                min-height: 100px !important;
                padding: 15px !important;
                text-align: left !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: flex-start !important;
                justify-content: space-between !important;
            }
            </style>
        """, unsafe_allow_html=True)

        for row_start in range(0, len(coverage_cards), 4):
            row_cards = coverage_cards[row_start:row_start + 4]
            cols = st.columns(len(row_cards), gap="medium")
            for idx, card in enumerate(row_cards):
                with cols[idx]:
                    is_active = st.session_state["coverage_focus"] == card["id"]
                    
                    # Rótulo dinâmico para o botão
                    btn_label = f"**{card['title']}**\n\n{card['value']}"
                    if is_active:
                        btn_label = f"📍 {btn_label}"
                    
                    if st.button(btn_label, key=f"coverage_card_{card['id']}", use_container_width=True, type="primary" if is_active else "secondary"):
                        st.session_state["coverage_focus"] = card["id"]
                        st.rerun()

                    st.markdown(
                        f"<div style='margin-top:0.4rem; padding: 0 0.5rem; color:#5d6c88; font-size:0.85rem; line-height:1.3; min-height: 3rem;'>{card['summary']}</div>",
                        unsafe_allow_html=True,
                    )

        selected_card = next(card for card in coverage_cards if card["id"] == st.session_state["coverage_focus"])

        st.markdown(f"""
            <div style="background: rgba(255,255,255,0.8); backdrop-filter: blur(10px); border-radius: 24px; padding: 20px; border: 1px solid rgba(31,47,99,0.08); box-shadow: 0 12px 32px rgba(6,12,48,0.08); margin: 1.5rem 0 1rem 0;">
                <span class="eyebrow">DETALHAMENTO</span>
                <h3 style="margin: 5px 0 10px 0; color: {CEB_NAVY_900};">{selected_card['title']}</h3>
                <p style="color: #53617e; font-size: 1rem; margin-bottom: 0;">{selected_card['detail']}</p>
            </div>
        """, unsafe_allow_html=True)

        selected_table = selected_card.get("table")
        
        # Área de ações e métrica rápida
        act_col1, act_col2 = st.columns([1, 4])
        with act_col1:
            st.metric("Valor atual", selected_card["value"], border=True)
        
        with act_col2:
            if selected_card["id"] == "formation" and not formation_issues_df.empty:
                st.write("") # Spacer
                st.download_button(
                    "📥 Baixar Lista de Pendências (CSV)",
                    formation_issues_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"pendencias_formacao_{current_year}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            elif selected_card["id"] == "experience" and not experience_issues_df.empty:
                st.write("") # Spacer
                st.download_button(
                    "📥 Baixar Lista de Pendências (CSV)",
                    experience_issues_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"pendencias_experiencia_{current_year}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            elif selected_card["id"] == "training" and not training_issues_df.empty:
                st.write("") # Spacer
                st.download_button(
                    "📥 Baixar Lista de Pendências (CSV)",
                    training_issues_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"pendencias_capacitacao_{current_year}.csv",
                    mime="text/csv",
                    use_container_width=True
                )

        if isinstance(selected_table, pd.DataFrame) and not selected_table.empty:
            # Expander para a tabela caso fique muito grande
            with st.expander("Ver lista detalhada", expanded=True):
                st.dataframe(_sanitize_dataframe_for_streamlit(selected_table), width="stretch", hide_index=True)
        else:
            st.info(selected_card["empty_text"])

    with tab_municSemCoord:
        _render_section_header(
            "Municipios sem Coordenador Municipal",
            "Leitura de municipios do ENEM 2026 que nao possuem coordenador municipal indicado/alocado.",
        )

        municSemCoord_df = pd.DataFrame(municipalities_without_coordinator)
        
        if municSemCoord_df.empty:
            st.success("✅ Todos os municipios possuem coordenador municipal indicado! Parabens!")
        else:
            total_munics_sem_coord = int(municSemCoord_df["qtd_municipios_sem_coordenador"].sum())
            total_ufs_afetadas = len(municSemCoord_df)
            taxa_cobertura = (
                (metrics.get("municipios_com_coordenador", 0) / 
                 (metrics.get("municipios_com_coordenador", 0) + total_munics_sem_coord) * 100)
                if (metrics.get("municipios_com_coordenador", 0) + total_munics_sem_coord) > 0
                else 0
            )

            m1, m2, m3, m4 = st.columns(4)
            m1.metric(
                "Total de Municipios",
                total_munics_sem_coord,
                "Sem coordenador municipal",
                border=True,
            )
            m2.metric(
                "UFs Afetadas",
                total_ufs_afetadas,
                "Estados com cobertura incompleta",
                border=True,
            )
            m3.metric(
                "Taxa de Cobertura",
                f"{taxa_cobertura:.1f}%".replace(".", ","),
                "De coordenadores indicados",
                border=True,
            )
            m4.metric(
                "Acao Necessaria",
                "SIM" if total_munics_sem_coord > 0 else "NAO",
                "Alocacao de coordenadores",
                border=True,
            )

            st.markdown("---")
            st.subheader("Resumo por UF")
            resumo_uf_df = municSemCoord_df[["uf", "qtd_municipios_sem_coordenador"]].copy()
            resumo_uf_df.columns = ["Estado (UF)", "Quantidade de Municipios"]
            st.dataframe(_sanitize_dataframe_for_streamlit(resumo_uf_df), width="stretch", hide_index=True)

            st.markdown("---")
            st.subheader("Lista Detalhada de Municipios sem Coordenador")
            
            for _, row in municSemCoord_df.iterrows():
                uf = row["uf"]
                municipios = row.get("municipios", [])
                
                if isinstance(municipios, str):
                    municipios = [m.strip() for m in municipios.split(",")]
                
                with st.expander(f"📍 {uf} - {len(municipios)} municipio(s)", expanded=False):
                    cols = st.columns(3)
                    for idx, municipio in enumerate(municipios):
                        col_idx = idx % 3
                        with cols[col_idx]:
                            st.write(f"• {municipio}")

    with tab_collaborators:
        _render_section_header("Consulta de Colaborador", "Busque por nome ou CPF para visualizar todos os dados disponíveis do colaborador.")
        
        collaborators_list = all_collaborators if all_collaborators else []
        collaborators_list = [
            {
                **collab,
                "cpf": _normalize_cpf_display(collab.get("cpf")),
                "cpf_formatado": _format_cpf(_normalize_cpf_display(collab.get("cpf"))),
            }
            for collab in collaborators_list
        ]
        
        # Filtrar apenas colaboradores indicados/alocados em 2026
        collaborators_list = [
            c for c in collaborators_list
            if c.get("funcao_2026") and str(c.get("funcao_2026", "")).strip()
        ]
        
        if not collaborators_list:
            st.info("Nenhum colaborador encontrado nos relatórios.")
        else:
            funcoes_disponiveis = sorted(
                {
                    str(funcao).strip()
                    for collab in collaborators_list
                    for funcao in [collab.get("funcao_2026", "")]
                    if str(funcao).strip()
                }
            )

            col_search, col_filter = st.columns([3, 1])

            with col_filter:
                funcao_filter = st.selectbox(
                    "Filtro por Função:",
                    options=["Todas as funções", *funcoes_disponiveis],
                    index=0,
                    key="collab_type_filter"
                )

            if funcao_filter != "Todas as funções":
                filtered = [
                    c
                    for c in collaborators_list
                    if funcao_filter == str(c.get('funcao_2026', '')).strip()
                ]
            else:
                filtered = collaborators_list

            # Preparar dados para busca respeitando o filtro de função
            search_terms = [
                f"{c['nome']} ({c.get('cpf_formatado') or _format_cpf(c.get('cpf'))})" if c.get('cpf') else c['nome']
                for c in filtered
            ]

            with col_search:
                search_input = st.selectbox(
                    "🔍 Busque por nome ou CPF do colaborador:",
                    options=search_terms,
                    index=None,
                    placeholder="Digite para buscar...",
                    key="collab_search"
                )

            if search_input:
                # Encontrar o colaborador selecionado dentro da lista filtrada
                selected_collab = None
                for collab in filtered:
                    label = f"{collab['nome']} ({collab.get('cpf_formatado') or _format_cpf(collab['cpf'])})" if collab.get('cpf') else collab['nome']
                    if label == search_input:
                        selected_collab = collab
                        break
                
                if selected_collab:
                    st.markdown("---")
                    st.markdown(f"### 👤 {selected_collab['nome']}")
                    
                    # Dados pessoais
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("CPF", selected_collab.get('cpf_formatado') or _format_cpf(selected_collab['cpf']) if selected_collab['cpf'] else "—")
                    with col2:
                        st.metric("Estado (UF)", selected_collab['uf'] if selected_collab['uf'] else "—")
                    with col3:
                        st.metric("Cidade", selected_collab['cidade'] if selected_collab['cidade'] else "—")
                    with col4:
                        st.metric("Status Geral", selected_collab['status'])
                    
                    st.markdown("---")
                    
                    # Dados 2026
                    st.subheader(f"Dados {current_year}")
                    col_2026_1, col_2026_2, col_2026_3, col_2026_4 = st.columns(4)
                    
                    with col_2026_1:
                        st.write("**Função**")
                        st.write(selected_collab['funcao_2026'] if selected_collab['funcao_2026'] else "—")
                    with col_2026_2:
                        st.write("**Escolaridade**")
                        st.write(selected_collab['escolaridade_2026'] if selected_collab['escolaridade_2026'] else "—")
                    with col_2026_3:
                        st.write("**Experiência**")
                        st.write(selected_collab['experiencia_2026'] if selected_collab['experiencia_2026'] else "—")
                    with col_2026_4:
                        st.write("**Capacitado**")
                        st.write(selected_collab['capacitado_2026'] if selected_collab['capacitado_2026'] else "—")
                    
                    if selected_collab['indicado_em_2026']:
                        st.caption(f"Indicado em: {selected_collab['indicado_em_2026']}")
                    
                    # Dados 2025 (se houver)
                    if selected_collab['funcao_2025'] or selected_collab['escolaridade_2025'] or selected_collab['experiencia_2025']:
                        st.markdown("---")
                        st.subheader(f"Dados {previous_year} (Histórico)")
                        col_2025_1, col_2025_2, col_2025_3, col_2025_4 = st.columns(4)
                        
                        with col_2025_1:
                            st.write("**Função**")
                            st.write(selected_collab['funcao_2025'] if selected_collab['funcao_2025'] else "—")
                        with col_2025_2:
                            st.write("**Escolaridade**")
                            st.write(selected_collab['escolaridade_2025'] if selected_collab['escolaridade_2025'] else "—")
                        with col_2025_3:
                            st.write("**Experiência**")
                            st.write(selected_collab['experiencia_2025'] if selected_collab['experiencia_2025'] else "—")
                        with col_2025_4:
                            st.write("**Capacitado**")
                            st.write(selected_collab['capacitado_2025'] if selected_collab['capacitado_2025'] else "—")
                        
                        if selected_collab['indicado_em_2025']:
                            st.caption(f"Indicado em: {selected_collab['indicado_em_2025']}")
                    
                    # Análise de mudanças
                    if selected_collab['funcao_2025'] and selected_collab['funcao_2026']:
                        st.markdown("---")
                        st.subheader("📊 Análise de Mudanças")
                        
                        if selected_collab['funcao_2025'] != selected_collab['funcao_2026']:
                            st.warning(f"⚠️ Mudança de função: {selected_collab['funcao_2025']} → {selected_collab['funcao_2026']}")
                        else:
                            st.success("✓ Função mantida na edição atual")
            
            else:
                st.info(f"Total de {len(filtered)} colaborador(es) encontrado(s). Selecione um para visualizar detalhes.")

                # Exibir resumo estatístico
                col_stats1, col_stats2, col_stats3 = st.columns(3)
                with col_stats1:
                    st.metric("Total geral", len(collaborators_list))
                with col_stats2:
                    st.metric("Funções distintas", len(funcoes_disponiveis))
                with col_stats3:
                    st.metric("Base da busca", len(filtered))

    with tab_subs:
        _render_section_header("Substituicoes", "Movimentacoes confirmadas na edicao corrente, com distribuicao por UF e funcao.")
        subs_df = pd.DataFrame(substitution_log)
        if not subs_df.empty and "ano" in subs_df.columns:
            subs_df = subs_df[subs_df["ano"] == current_year].copy()
        st.caption(f"Substituicoes registradas somente para a edicao {current_year}.")
        if subs_df.empty:
            st.info(f"Nenhum substituido encontrado para a edicao {current_year}.")
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total", len(subs_df))
            m2.metric("UFs", subs_df["uf"].nunique())
            m3.metric("Funcoes", subs_df["funcao"].nunique())

            subs_rows = subs_df.to_dict("records")
            col_u, col_f = st.columns(2)
            with col_u:
                st.dataframe(_sanitize_dataframe_for_streamlit(_stat_list(subs_rows, "uf", "UF")), width="stretch", hide_index=True)
            with col_f:
                st.dataframe(_sanitize_dataframe_for_streamlit(_stat_list(subs_rows, "funcao", "Funcao")), width="stretch", hide_index=True)

            st.dataframe(_sanitize_dataframe_for_streamlit(subs_df), width="stretch", hide_index=True)

    with tab_map:
        _render_section_header("Mapa do Brasil", "Distribuicao geografica dos coordenadores indicados para leitura territorial da operacao.")
        _render_map(charts.get("coordinator_by_uf", []))
        map_table = pd.DataFrame(charts.get("coordinator_by_uf", []))
        if not map_table.empty:
            st.dataframe(_sanitize_dataframe_for_streamlit(map_table), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
