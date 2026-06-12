#!/usr/bin/env python3
"""
folder_analyzer.py
──────────────────
지정 경로의 폴더 구조·패턴·용량을 분석하고 HTML 리포트를 생성합니다.

사용법:
    python folder_analyzer.py <분석할_경로> [--output <리포트_경로>]

예시:
    python folder_analyzer.py /Users/me/projects
    python folder_analyzer.py /Users/me/projects --output report.html
"""

import os
import sys
import json
import datetime
from pathlib import Path
from collections import defaultdict


# ──────────────────────────────────────────────
# 1. 데이터 수집
# ──────────────────────────────────────────────

def human_size(size_bytes: int) -> str:
    """바이트 → 사람이 읽기 좋은 단위로 변환."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def get_dir_size(path: Path) -> int:
    """디렉터리 총 용량 (재귀)."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                try:
                    total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
            elif entry.is_dir(follow_symlinks=False):
                total += get_dir_size(Path(entry.path))
    except PermissionError:
        pass
    return total


def build_tree(path: Path, depth: int = 0) -> dict:
    """
    재귀적으로 폴더 트리를 딕셔너리로 구성.
    반환 형태:
    {
        "name": str,
        "path": str,
        "depth": int,
        "size": int,          # 이 노드 하위 전체 용량
        "file_count": int,    # 직계 파일 수
        "children": [...]     # 하위 폴더 목록
    }
    """
    node = {
        "name": path.name or str(path),
        "path": str(path),
        "depth": depth,
        "size": 0,
        "file_count": 0,
        "children": [],
    }

    try:
        entries = list(os.scandir(path))
    except PermissionError:
        node["name"] += " [접근 권한 없음]"
        return node

    for entry in sorted(entries, key=lambda e: (not e.is_dir(), e.name.lower())):
        if entry.is_symlink():
            continue
        if entry.is_file(follow_symlinks=False):
            try:
                node["file_count"] += 1
                node["size"] += entry.stat(follow_symlinks=False).st_size
            except OSError:
                pass
        elif entry.is_dir(follow_symlinks=False):
            child = build_tree(Path(entry.path), depth + 1)
            node["size"] += child["size"]
            node["children"].append(child)

    return node


def collect_stats(tree: dict, stats: dict | None = None) -> dict:
    """트리 전체를 순회하며 통계 수집."""
    if stats is None:
        stats = {
            "total_folders": 0,
            "total_files": 0,
            "total_size": 0,
            "max_depth": 0,
            "depth_distribution": defaultdict(int),   # depth → 폴더 수
            "largest_dirs": [],                        # (size, path) 상위 목록
            "name_patterns": defaultdict(int),         # 첫 번째 토큰 → 등장 횟수
        }

    stats["total_folders"] += 1
    stats["total_files"] += tree["file_count"]
    stats["total_size"] += tree["file_count"]  # 파일 수 누적은 위에서
    stats["max_depth"] = max(stats["max_depth"], tree["depth"])
    stats["depth_distribution"][tree["depth"]] += 1
    stats["largest_dirs"].append((tree["size"], tree["path"]))

    # 이름 패턴: 소문자 변환 + 첫 토큰(숫자 제외)
    clean = tree["name"].lower().replace("-", "_").replace(" ", "_")
    token = clean.split("_")[0] if "_" in clean else clean[:8]
    if token:
        stats["name_patterns"][token] += 1

    for child in tree["children"]:
        collect_stats(child, stats)

    return stats


# ──────────────────────────────────────────────
# 2. HTML 리포트 생성
# ──────────────────────────────────────────────

def tree_to_html(node: dict, max_size: int) -> str:
    """단일 노드를 <li> HTML 문자열로 변환 (재귀)."""
    pct = (node["size"] / max_size * 100) if max_size else 0
    bar_width = max(pct, 0.5)
    size_str = human_size(node["size"])
    fc = node["file_count"]

    has_children = bool(node["children"])
    toggle = "▶" if has_children else "·"
    open_attr = ' open' if node["depth"] < 2 else ''

    children_html = ""
    if has_children:
        children_html = "<ul class='subtree'>" + "".join(
            tree_to_html(c, max_size) for c in node["children"]
        ) + "</ul>"

    details_tag = f"<details{open_attr}>" if has_children else "<div>"
    details_close = "</details>" if has_children else "</div>"
    summary_or_div = "summary" if has_children else "div"

    return f"""
<li class="node d{node['depth']}">
  {details_tag}
    <{summary_or_div} class="node-row">
      <span class="toggle">{toggle}</span>
      <span class="name" title="{node['path']}">{node['name']}</span>
      <span class="meta">{fc} 파일</span>
      <span class="size-label">{size_str}</span>
      <span class="bar-wrap"><span class="bar" style="width:{bar_width:.1f}%"></span></span>
    </{summary_or_div}>
    {children_html}
  {details_close}
</li>"""


def build_html(root: dict, stats: dict, target_path: str) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    max_size = root["size"] or 1

    # 상위 10 폴더
    top10 = sorted(stats["largest_dirs"], key=lambda x: x[0], reverse=True)[:10]
    top10_html = "".join(
        f"<tr><td class='path'>{p}</td><td class='sz'>{human_size(s)}</td></tr>"
        for s, p in top10
    )

    # depth 분포 차트용 데이터
    depth_dist = dict(sorted(stats["depth_distribution"].items()))
    depth_labels = json.dumps(list(depth_dist.keys()))
    depth_values = json.dumps(list(depth_dist.values()))

    # 이름 패턴 상위 15개
    top_patterns = sorted(stats["name_patterns"].items(), key=lambda x: x[1], reverse=True)[:15]
    pattern_labels = json.dumps([p for p, _ in top_patterns])
    pattern_values = json.dumps([c for _, c in top_patterns])

    # 트리 HTML
    tree_html = "<ul class='tree'>" + tree_to_html(root, max_size) + "</ul>"

    total_folders = stats["total_folders"]
    total_files = stats["total_files"]
    total_size = human_size(root["size"])
    max_depth = stats["max_depth"]

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>폴더 구조 분석 · {target_path}</title>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #22263a;
    --accent: #6ee7f7;
    --accent2: #a78bfa;
    --text: #e2e8f0;
    --muted: #64748b;
    --bar-bg: #1e2235;
    --bar-fill: linear-gradient(90deg, #6ee7f7, #a78bfa);
    --border: #2d3250;
    --radius: 10px;
    --font-mono: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    --font-sans: 'Pretendard', 'Noto Sans KR', -apple-system, sans-serif;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.6;
    padding: 32px 24px;
  }}
  h1 {{ font-size: 22px; font-weight: 700; color: var(--accent); letter-spacing: -0.02em; }}
  h2 {{ font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase;
        letter-spacing: 0.08em; margin-bottom: 14px; }}
  .meta-line {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
  .meta-line span {{ color: var(--text); font-family: var(--font-mono); }}

  /* ── 요약 카드 ── */
  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    margin: 28px 0;
  }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
  }}
  .card .label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.07em; }}
  .card .value {{
    font-size: 28px; font-weight: 700; font-family: var(--font-mono);
    background: var(--bar-fill); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }}

  /* ── 섹션 ── */
  .section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 22px 24px;
    margin-bottom: 20px;
  }}

  /* ── 차트 ── */
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
  @media (max-width: 700px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  canvas {{ max-height: 220px; }}

  /* ── Top 10 테이블 ── */
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid var(--border); }}
  td.path {{ font-family: var(--font-mono); color: var(--text); word-break: break-all; }}
  td.sz {{ font-family: var(--font-mono); color: var(--accent); white-space: nowrap; text-align: right; }}
  tr:last-child td {{ border-bottom: none; }}

  /* ── 트리 ── */
  .tree, .subtree {{ list-style: none; padding-left: 20px; }}
  .tree {{ padding-left: 0; }}
  .node {{ margin: 1px 0; }}
  .node-row {{
    display: flex; align-items: center; gap: 8px;
    padding: 4px 8px; border-radius: 6px; cursor: pointer;
    white-space: nowrap; overflow: hidden;
  }}
  .node-row:hover {{ background: var(--surface2); }}
  details > summary {{ list-style: none; }}
  details > summary::-webkit-details-marker {{ display: none; }}
  .toggle {{ font-size: 10px; color: var(--muted); width: 12px; flex-shrink: 0; }}
  .name {{
    font-family: var(--font-mono); font-size: 13px;
    flex: 0 1 auto; overflow: hidden; text-overflow: ellipsis; min-width: 0;
  }}
  .meta {{ font-size: 11px; color: var(--muted); flex-shrink: 0; }}
  .size-label {{ font-size: 11px; color: var(--accent); flex-shrink: 0; min-width: 70px; text-align: right; }}
  .bar-wrap {{ flex: 1; height: 4px; background: var(--bar-bg); border-radius: 2px; min-width: 40px; }}
  .bar {{ height: 100%; background: var(--bar-fill); border-radius: 2px; transition: width 0.3s; }}

  /* depth별 들여쓰기 색조 */
  .d0 > details > summary .name,
  .d0 > div > .name {{ color: var(--accent); font-weight: 600; }}
  .d1 > details > summary .name,
  .d1 > div > .name {{ color: #93c5fd; }}

  /* ── 검색 ── */
  .search-wrap {{ margin-bottom: 12px; }}
  #search {{
    width: 100%; padding: 9px 14px;
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; color: var(--text);
    font-family: var(--font-mono); font-size: 13px;
    outline: none;
  }}
  #search:focus {{ border-color: var(--accent); }}
  .hidden {{ display: none !important; }}
</style>
</head>
<body>

<h1>📁 폴더 구조 분석 리포트</h1>
<p class="meta-line">대상 경로: <span>{target_path}</span> &nbsp;·&nbsp; 생성 시각: <span>{now}</span></p>

<!-- 요약 카드 -->
<div class="cards">
  <div class="card"><div class="label">총 폴더 수</div><div class="value">{total_folders:,}</div></div>
  <div class="card"><div class="label">총 파일 수</div><div class="value">{total_files:,}</div></div>
  <div class="card"><div class="label">전체 용량</div><div class="value">{total_size}</div></div>
  <div class="card"><div class="label">최대 깊이</div><div class="value">{max_depth}</div></div>
</div>

<!-- 차트 -->
<div class="charts">
  <div class="section">
    <h2>깊이(depth)별 폴더 분포</h2>
    <canvas id="depthChart"></canvas>
  </div>
  <div class="section">
    <h2>폴더명 패턴 Top 15</h2>
    <canvas id="patternChart"></canvas>
  </div>
</div>

<!-- 용량 Top 10 -->
<div class="section">
  <h2>용량 상위 10개 폴더</h2>
  <table>{top10_html}</table>
</div>

<!-- 트리 뷰 -->
<div class="section">
  <h2>폴더 트리 (클릭으로 펼치기/접기)</h2>
  <div class="search-wrap">
    <input id="search" type="text" placeholder="폴더명 검색...">
  </div>
  {tree_html}
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const chartDefaults = {{
  color: '#94a3b8',
  borderColor: '#2d3250',
  font: {{ family: "'JetBrains Mono', monospace", size: 11 }},
}};
Chart.defaults.color = chartDefaults.color;

// 깊이 분포 차트
new Chart(document.getElementById('depthChart'), {{
  type: 'bar',
  data: {{
    labels: {depth_labels},
    datasets: [{{
      label: '폴더 수',
      data: {depth_values},
      backgroundColor: 'rgba(110,231,247,0.25)',
      borderColor: '#6ee7f7',
      borderWidth: 1.5,
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#1e2235' }}, ticks: {{ font: chartDefaults.font }} }},
      y: {{ grid: {{ color: '#1e2235' }}, ticks: {{ font: chartDefaults.font }} }},
    }}
  }}
}});

// 패턴 차트
new Chart(document.getElementById('patternChart'), {{
  type: 'bar',
  data: {{
    labels: {pattern_labels},
    datasets: [{{
      label: '등장 횟수',
      data: {pattern_values},
      backgroundColor: 'rgba(167,139,250,0.25)',
      borderColor: '#a78bfa',
      borderWidth: 1.5,
      borderRadius: 4,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ grid: {{ color: '#1e2235' }}, ticks: {{ font: chartDefaults.font }} }},
      y: {{ grid: {{ color: '#1e2235' }}, ticks: {{ font: chartDefaults.font }} }},
    }}
  }}
}});

// 트리 검색
document.getElementById('search').addEventListener('input', function() {{
  const q = this.value.trim().toLowerCase();
  document.querySelectorAll('.node').forEach(li => {{
    if (!q) {{ li.classList.remove('hidden'); return; }}
    const name = li.querySelector('.name')?.textContent.toLowerCase() || '';
    li.classList.toggle('hidden', !name.includes(q));
  }});
}});
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# 3. 메인
# ──────────────────────────────────────────────

def prompt_path() -> Path:
    """경로를 입력받아 검증 후 반환. 잘못된 경로는 재입력 요청."""
    while True:
        raw = input("\n📂 분석할 폴더 경로를 입력하세요: ").strip()
        if not raw:
            print("   ⚠️  경로를 입력해 주세요.")
            continue
        # 따옴표 제거 (드래그 앤 드롭 등으로 붙여넣을 때 포함되는 경우 대비)
        raw = raw.strip("'\"")
        target = Path(raw).expanduser().resolve()
        if not target.exists():
            print(f"   ❌ 경로를 찾을 수 없습니다: {target}")
            continue
        if not target.is_dir():
            print(f"   ❌ 폴더가 아닙니다: {target}")
            continue
        return target


def main():
    print("=" * 50)
    print("  폴더 구조·패턴·용량 분석기")
    print("=" * 50)

    target = prompt_path()

    # 출력 파일은 분석 대상 폴더와 같은 위치에 생성
    out_name = f"folder_report_{target.name}.html"
    out_path = Path(out_name)

    print(f"\n🔍 분석 시작: {target}")
    print("   (폴더가 많을 경우 수 초 ~ 수십 초 소요될 수 있습니다)")

    tree = build_tree(target)
    stats = collect_stats(tree)

    # total_files 재계산 (build_tree가 누적하므로 여기서 재집계)
    def count_files(node):
        return node["file_count"] + sum(count_files(c) for c in node["children"])

    stats["total_files"] = count_files(tree)

    html = build_html(tree, stats, str(target))

    out_path.write_text(html, encoding="utf-8")

    print(f"\n✅ 리포트 생성 완료!")
    print(f"   파일: {out_path.resolve()}")
    print(f"\n📊 요약")
    print(f"   총 폴더 수  : {stats['total_folders']:,}")
    print(f"   총 파일 수  : {stats['total_files']:,}")
    print(f"   전체 용량   : {human_size(tree['size'])}")
    print(f"   최대 깊이   : {stats['max_depth']}")


if __name__ == "__main__":
    main()
