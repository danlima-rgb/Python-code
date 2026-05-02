#!/usr/bin/env python3
"""
Web Scraper - Extrai HTML, CSS, React e Tailwind de qualquer site.
Uso: python web_scraper.py <URL> [--output <pasta>]
"""

import re
import sys
import json
import argparse
import urllib.parse
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ── Tailwind: prefixos e variantes conhecidos ──────────────────────────────────
TAILWIND_PREFIXES = {
    "layout": ["container", "block", "inline", "flex", "grid", "hidden",
                "overflow", "position", "static", "fixed", "absolute",
                "relative", "sticky", "top-", "right-", "bottom-", "left-",
                "z-", "float-", "clear-", "isolation-", "object-", "inset-"],
    "spacing": ["p-", "px-", "py-", "pt-", "pr-", "pb-", "pl-",
                "m-", "mx-", "my-", "mt-", "mr-", "mb-", "ml-",
                "space-", "gap-"],
    "sizing": ["w-", "h-", "min-w-", "min-h-", "max-w-", "max-h-", "size-"],
    "typography": ["font-", "text-", "tracking-", "leading-", "list-",
                   "decoration-", "underline", "italic", "uppercase",
                   "lowercase", "capitalize", "truncate", "whitespace-",
                   "break-", "indent-"],
    "background": ["bg-", "from-", "via-", "to-", "gradient-"],
    "border": ["border", "border-", "rounded", "rounded-", "ring", "ring-",
               "outline", "outline-", "divide-"],
    "effects": ["shadow", "shadow-", "opacity-", "blur-", "drop-shadow-",
                "grayscale", "invert", "sepia", "brightness-", "contrast-",
                "saturate-", "hue-rotate-", "mix-blend-", "bg-blend-"],
    "transitions": ["transition", "transition-", "duration-", "ease-",
                    "delay-", "animate-"],
    "transforms": ["scale-", "rotate-", "translate-", "skew-", "origin-"],
    "interactivity": ["cursor-", "select-", "resize", "resize-", "appearance-",
                      "pointer-events-", "will-change-", "scroll-",
                      "touch-action-"],
    "flexbox_grid": ["flex-", "basis-", "grow", "grow-", "shrink", "shrink-",
                     "order-", "grid-", "col-", "row-", "auto-cols-",
                     "auto-rows-", "place-", "justify-", "content-",
                     "items-", "self-"],
    "accessibility": ["sr-only", "not-sr-only", "focus-", "focus:", "hover:",
                      "active:", "visited:", "disabled:"],
}

TAILWIND_VARIANTS = [
    "hover:", "focus:", "active:", "group-hover:", "group-focus:",
    "focus-within:", "focus-visible:", "disabled:", "checked:", "first:",
    "last:", "odd:", "even:", "sm:", "md:", "lg:", "xl:", "2xl:",
    "dark:", "motion-safe:", "motion-reduce:", "print:",
]

# ── React: padrões de detecção ────────────────────────────────────────────────
REACT_DATA_ATTRS = ["data-reactroot", "data-reactid", "data-react-helmet",
                    "__reactfiber", "__reactprops", "_reactrootcontainer"]

REACT_SCRIPT_PATTERNS = [
    r"react(?:\.min)?\.js", r"react-dom(?:\.min)?\.js",
    r"react\.development\.js", r"react\.production\.min\.js",
    r"_next/", r"__next", r"next\.js",
    r"gatsby", r"remix", r"create-react-app",
]

REACT_GLOBAL_PATTERNS = [
    r"window\.__NEXT_DATA__", r"window\.__NUXT__", r"window\.React",
    r"window\.__REACT_DEVTOOLS", r"__webpack_require__",
    r"window\.__remixContext",
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fetch(url: str, timeout: int = 20) -> requests.Response:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def _fetch_text(url: str) -> str:
    try:
        return _fetch(url).text
    except Exception:
        return ""


def _is_tailwind_class(cls: str) -> bool:
    stripped = cls
    for v in TAILWIND_VARIANTS:
        if cls.startswith(v):
            stripped = cls[len(v):]
            break
    for prefixes in TAILWIND_PREFIXES.values():
        for p in prefixes:
            if stripped == p.rstrip("-") or stripped.startswith(p):
                return True
    return False


def _categorize_tailwind(cls: str) -> str:
    stripped = cls
    for v in TAILWIND_VARIANTS:
        if cls.startswith(v):
            stripped = cls[len(v):]
            break
    for category, prefixes in TAILWIND_PREFIXES.items():
        for p in prefixes:
            if stripped == p.rstrip("-") or stripped.startswith(p):
                return category
    return "other"


# ──────────────────────────────────────────────────────────────────────────────
# Extractor principal
# ──────────────────────────────────────────────────────────────────────────────

class WebScraper:
    def __init__(self, url: str):
        self.url = url
        self.base_url = self._base(url)
        self.html_raw: str = ""
        self.soup: BeautifulSoup = None
        self.result: dict = {}

    # ── Setup ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _base(url: str) -> str:
        p = urllib.parse.urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    def _abs_url(self, href: str) -> str:
        if not href:
            return ""
        return urllib.parse.urljoin(self.base_url, href)

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def fetch(self) -> None:
        print(f"[+] Baixando: {self.url}")
        resp = _fetch(self.url)
        self.html_raw = resp.text
        self.soup = BeautifulSoup(self.html_raw, "lxml")
        print(f"    Status: {resp.status_code} | Tamanho: {len(self.html_raw):,} bytes")

    # ── HTML ──────────────────────────────────────────────────────────────────

    def extract_html(self) -> dict:
        print("[+] Extraindo HTML...")
        soup = self.soup

        meta = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or tag.get("http-equiv", "")
            content = tag.get("content", "")
            if name:
                meta[name] = content

        links = [
            {"text": a.get_text(strip=True), "href": self._abs_url(a.get("href", ""))}
            for a in soup.find_all("a", href=True)
        ]

        images = [
            {
                "src": self._abs_url(img.get("src", "")),
                "alt": img.get("alt", ""),
                "width": img.get("width", ""),
                "height": img.get("height", ""),
            }
            for img in soup.find_all("img")
        ]

        headings = defaultdict(list)
        for level in range(1, 7):
            for h in soup.find_all(f"h{level}"):
                headings[f"h{level}"].append(h.get_text(strip=True))

        scripts = []
        for s in soup.find_all("script"):
            entry = {"type": s.get("type", ""), "src": self._abs_url(s.get("src", ""))}
            if not s.get("src"):
                entry["inline_length"] = len(s.get_text())
            scripts.append(entry)

        forms = []
        for form in soup.find_all("form"):
            fields = [
                {"tag": inp.name, "type": inp.get("type", ""), "name": inp.get("name", "")}
                for inp in form.find_all(["input", "textarea", "select", "button"])
            ]
            forms.append({"action": self._abs_url(form.get("action", "")),
                          "method": form.get("method", "get").upper(),
                          "fields": fields})

        tag_count = defaultdict(int)
        for tag in soup.find_all(True):
            tag_count[tag.name] += 1

        return {
            "title": soup.title.string.strip() if soup.title and soup.title.string else "",
            "lang": soup.html.get("lang", "") if soup.html else "",
            "charset": soup.find("meta", charset=True) and soup.find("meta", charset=True).get("charset", ""),
            "meta_tags": meta,
            "headings": dict(headings),
            "links_total": len(links),
            "links": links[:100],
            "images_total": len(images),
            "images": images[:50],
            "scripts_total": len(scripts),
            "scripts": scripts,
            "forms": forms,
            "tag_frequency": dict(sorted(tag_count.items(), key=lambda x: -x[1])[:30]),
        }

    # ── CSS ───────────────────────────────────────────────────────────────────

    def extract_css(self) -> dict:
        print("[+] Extraindo CSS...")
        soup = self.soup

        # CSS externo
        external_sheets = []
        for link in soup.find_all("link", rel=lambda r: r and "stylesheet" in r):
            href = self._abs_url(link.get("href", ""))
            if href:
                external_sheets.append(href)

        # <style> internos
        internal_blocks = [s.get_text() for s in soup.find_all("style") if s.get_text(strip=True)]

        # Estilos inline
        inline_styles = {}
        for tag in soup.find_all(style=True):
            key = f"{tag.name}#{tag.get('id', '')} .{' '.join(tag.get('class', []))}"
            inline_styles[key.strip()] = tag["style"]

        # Baixar e analisar CSS externo
        all_css_text = "\n".join(internal_blocks)
        fetched_sheets = {}
        for url in external_sheets[:5]:  # limite para não sobrecarregar
            print(f"    Baixando CSS: {url}")
            css_text = _fetch_text(url)
            if css_text:
                fetched_sheets[url] = len(css_text)
                all_css_text += "\n" + css_text

        # Extrair variáveis CSS
        css_vars = re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", all_css_text)
        css_variables = {k.strip(): v.strip() for k, v in css_vars}

        # Extrair seletores
        selectors = re.findall(r"([^{}]+)\s*\{[^{}]*\}", all_css_text)
        clean_selectors = [s.strip() for s in selectors if s.strip() and not s.strip().startswith("@")]

        # Media queries
        media_queries = re.findall(r"@media\s*([^{]+)\{", all_css_text)

        # Keyframes
        keyframes = re.findall(r"@keyframes\s+([\w-]+)", all_css_text)

        # Imports
        imports = re.findall(r"@import\s+['\"]([^'\"]+)['\"]", all_css_text)

        # Fontes
        font_faces = re.findall(r"font-family\s*:\s*['\"]?([^;'\"]+)['\"]?;", all_css_text)
        font_families = list({f.strip().strip("'\"") for f in font_faces})

        # Cores
        colors_hex = list(set(re.findall(r"#([0-9a-fA-F]{3,8})\b", all_css_text)))
        colors_rgb = list(set(re.findall(r"rgba?\([^)]+\)", all_css_text)))

        return {
            "external_stylesheets": external_sheets,
            "external_stylesheets_fetched": fetched_sheets,
            "internal_style_blocks": len(internal_blocks),
            "inline_styles_count": len(inline_styles),
            "inline_styles_sample": dict(list(inline_styles.items())[:20]),
            "css_variables": css_variables,
            "selectors_total": len(clean_selectors),
            "selectors_sample": clean_selectors[:50],
            "media_queries": [mq.strip() for mq in media_queries],
            "keyframes": keyframes,
            "imports": imports,
            "font_families": font_families,
            "colors_hex": colors_hex[:50],
            "colors_rgb": colors_rgb[:30],
        }

    # ── React ─────────────────────────────────────────────────────────────────

    def extract_react(self) -> dict:
        print("[+] Extraindo React...")
        soup = self.soup
        html_text = self.html_raw

        signals = []

        # Atributos data-react* no DOM
        data_attrs_found = []
        for attr in REACT_DATA_ATTRS:
            tags = soup.find_all(attrs={attr: True})
            if tags:
                data_attrs_found.append(attr)
                signals.append(f"Atributo DOM: {attr}")

        # Scripts React/Next/Gatsby
        script_matches = []
        for script in soup.find_all("script", src=True):
            src = script.get("src", "")
            for pattern in REACT_SCRIPT_PATTERNS:
                if re.search(pattern, src, re.IGNORECASE):
                    script_matches.append(src)
                    signals.append(f"Script: {src}")
                    break

        # Globals no HTML bruto
        globals_found = []
        for pattern in REACT_GLOBAL_PATTERNS:
            if re.search(pattern, html_text):
                globals_found.append(pattern)
                signals.append(f"Global: {pattern}")

        # __NEXT_DATA__ (Next.js)
        next_data = {}
        next_match = re.search(r"__NEXT_DATA__\s*=\s*(\{.+?\})\s*</script>", html_text, re.DOTALL)
        if next_match:
            try:
                next_data = json.loads(next_match.group(1))
            except json.JSONDecodeError:
                next_data = {"raw_length": len(next_match.group(1))}

        # Hydration markers
        hydration = bool(re.search(r"<!--\s*\$(!|[a-z0-9]+)?\s*-->", html_text))
        if hydration:
            signals.append("Hydration markers (React 18+)")

        # Props/state nos scripts inline
        component_patterns = re.findall(
            r"(?:useState|useEffect|useRef|useCallback|useMemo|useContext|useReducer)\s*\(",
            html_text,
        )
        hook_counts = defaultdict(int)
        for h in re.findall(
            r"(useState|useEffect|useRef|useCallback|useMemo|useContext|useReducer|useLayoutEffect|useId|useDeferredValue|useTransition)\s*\(",
            html_text,
        ):
            hook_counts[h] += 1
        if hook_counts:
            signals.append(f"React hooks detectados: {list(hook_counts.keys())}")

        # Verifica frameworks baseados em React
        framework = "React"
        if re.search(r"_next/", html_text) or "__NEXT_DATA__" in html_text:
            framework = "Next.js"
        elif re.search(r"gatsby", html_text, re.IGNORECASE):
            framework = "Gatsby"
        elif re.search(r"__remixContext", html_text):
            framework = "Remix"
        elif re.search(r"__nuxt|window\.__NUXT__", html_text):
            framework = "Nuxt.js (Vue)"

        detected = bool(signals)

        return {
            "detected": detected,
            "framework": framework if detected else "Não detectado",
            "signals": signals,
            "data_attributes_found": data_attrs_found,
            "react_scripts": script_matches,
            "globals_found": globals_found,
            "hooks_in_inline_scripts": dict(hook_counts),
            "hydration_markers": hydration,
            "next_data": next_data if next_data else None,
        }

    # ── Tailwind ──────────────────────────────────────────────────────────────

    def extract_tailwind(self) -> dict:
        print("[+] Extraindo Tailwind CSS...")
        soup = self.soup
        html_text = self.html_raw

        all_classes: list[str] = []
        for tag in soup.find_all(True):
            all_classes.extend(tag.get("class", []))

        tw_classes = [c for c in all_classes if _is_tailwind_class(c)]
        tw_unique = sorted(set(tw_classes))

        # Categorizar
        categorized: dict[str, list[str]] = defaultdict(list)
        for cls in tw_unique:
            cat = _categorize_tailwind(cls)
            if cls not in categorized[cat]:
                categorized[cat].append(cls)

        # Variantes responsivas usadas
        responsive_variants = sorted({
            cls.split(":")[0] + ":"
            for cls in tw_unique
            if ":" in cls and cls.split(":")[0] in ["sm", "md", "lg", "xl", "2xl"]
        })

        # Dark mode
        dark_classes = [c for c in tw_unique if c.startswith("dark:")]

        # Detectar config Tailwind
        tw_config_urls = [
            s.get("src", "")
            for s in soup.find_all("script", src=True)
            if "tailwind" in s.get("src", "").lower()
        ]
        cdn_detected = bool(tw_config_urls)

        # CDN via script src
        tw_cdn = any(
            "tailwindcss" in s.get("src", "") or "cdn.tailwindcss" in s.get("src", "")
            for s in soup.find_all("script", src=True)
        )

        # Verificar se tailwind está em classes de folha externa (heurística)
        tw_in_external = bool(tw_unique) and not cdn_detected

        # Frequência das classes
        freq = defaultdict(int)
        for c in tw_classes:
            freq[c] += 1
        top_classes = sorted(freq.items(), key=lambda x: -x[1])[:30]

        return {
            "detected": bool(tw_unique),
            "cdn_via_script": tw_cdn,
            "total_tw_class_uses": len(tw_classes),
            "unique_tw_classes": len(tw_unique),
            "classes_by_category": {k: sorted(v) for k, v in categorized.items()},
            "responsive_variants_used": responsive_variants,
            "dark_mode_classes": dark_classes,
            "top_classes_by_frequency": top_classes,
            "tailwind_script_urls": tw_config_urls,
        }

    # ── Run all ───────────────────────────────────────────────────────────────

    def run(self) -> dict:
        self.fetch()
        self.result = {
            "url": self.url,
            "scraped_at": datetime.now().isoformat(),
            "html": self.extract_html(),
            "css": self.extract_css(),
            "react": self.extract_react(),
            "tailwind": self.extract_tailwind(),
        }
        return self.result

    # ── Save ──────────────────────────────────────────────────────────────────

    def save(self, output_dir: str = "output") -> Path:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        domain = urllib.parse.urlparse(self.url).netloc.replace(".", "_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"{domain}_{ts}"

        # HTML bruto
        raw_path = out / f"{prefix}_raw.html"
        raw_path.write_text(self.html_raw, encoding="utf-8")

        # JSON completo
        json_path = out / f"{prefix}_data.json"
        json_path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8")

        # Relatório legível
        report_path = out / f"{prefix}_report.txt"
        report_path.write_text(self._build_report(), encoding="utf-8")

        print(f"\n[✓] Arquivos salvos em: {out.resolve()}")
        print(f"    HTML bruto : {raw_path.name}")
        print(f"    JSON dados : {json_path.name}")
        print(f"    Relatório  : {report_path.name}")

        return out

    def _build_report(self) -> str:
        r = self.result
        lines = [
            "=" * 70,
            "  WEB SCRAPER - RELATÓRIO COMPLETO",
            "=" * 70,
            f"URL        : {r['url']}",
            f"Extraído em: {r['scraped_at']}",
            "",
        ]

        # HTML
        h = r["html"]
        lines += [
            "─" * 70,
            "  HTML",
            "─" * 70,
            f"Título   : {h['title']}",
            f"Idioma   : {h['lang']}",
            f"Charset  : {h['charset']}",
            f"Links    : {h['links_total']}",
            f"Imagens  : {h['images_total']}",
            f"Scripts  : {h['scripts_total']}",
            f"Formulários: {len(h['forms'])}",
            "",
            "Meta Tags:",
        ]
        for k, v in h["meta_tags"].items():
            lines.append(f"  {k}: {v[:80]}")
        lines += ["", "Cabeçalhos:"]
        for level, texts in h["headings"].items():
            for t in texts[:5]:
                lines.append(f"  [{level.upper()}] {t[:80]}")
        lines += ["", "Tags mais frequentes:"]
        for tag, cnt in list(h["tag_frequency"].items())[:15]:
            lines.append(f"  <{tag}>: {cnt}")

        # CSS
        c = r["css"]
        lines += [
            "",
            "─" * 70,
            "  CSS",
            "─" * 70,
            f"Folhas externas  : {len(c['external_stylesheets'])}",
            f"Blocos internos  : {c['internal_style_blocks']}",
            f"Estilos inline   : {c['inline_styles_count']}",
            f"Variáveis CSS    : {len(c['css_variables'])}",
            f"Seletores        : {c['selectors_total']}",
            f"Media queries    : {len(c['media_queries'])}",
            f"Keyframes        : {len(c['keyframes'])}",
            f"Fontes           : {', '.join(c['font_families'][:10]) or 'N/A'}",
        ]
        if c["css_variables"]:
            lines.append("\nVariáveis CSS (primeiras 20):")
            for k, v in list(c["css_variables"].items())[:20]:
                lines.append(f"  {k}: {v}")
        lines += ["", "Folhas externas:"]
        for url in c["external_stylesheets"]:
            lines.append(f"  {url}")

        # React
        rx = r["react"]
        lines += [
            "",
            "─" * 70,
            "  REACT",
            "─" * 70,
            f"Detectado : {'Sim' if rx['detected'] else 'Não'}",
            f"Framework : {rx['framework']}",
            f"Hydration : {'Sim' if rx['hydration_markers'] else 'Não'}",
        ]
        if rx["signals"]:
            lines.append("Sinais detectados:")
            for s in rx["signals"]:
                lines.append(f"  • {s}")
        if rx["hooks_in_inline_scripts"]:
            lines.append("Hooks React:")
            for h_name, cnt in rx["hooks_in_inline_scripts"].items():
                lines.append(f"  {h_name}: {cnt}x")

        # Tailwind
        tw = r["tailwind"]
        lines += [
            "",
            "─" * 70,
            "  TAILWIND CSS",
            "─" * 70,
            f"Detectado      : {'Sim' if tw['detected'] else 'Não'}",
            f"Via CDN        : {'Sim' if tw['cdn_via_script'] else 'Não'}",
            f"Usos de classes: {tw['total_tw_class_uses']}",
            f"Classes únicas : {tw['unique_tw_classes']}",
            f"Variantes resp.: {', '.join(tw['responsive_variants_used']) or 'N/A'}",
            f"Dark mode      : {len(tw['dark_mode_classes'])} classes",
        ]
        lines.append("\nClasses por categoria:")
        for cat, classes in tw["classes_by_category"].items():
            lines.append(f"  [{cat}] ({len(classes)}): {', '.join(classes[:10])}")
        if tw["top_classes_by_frequency"]:
            lines.append("\nTop classes (frequência):")
            for cls, cnt in tw["top_classes_by_frequency"][:15]:
                lines.append(f"  {cls}: {cnt}x")

        lines += ["", "=" * 70]
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Baixa e extrai HTML, CSS, React e Tailwind de qualquer site."
    )
    parser.add_argument("url", help="URL do site (ex: https://exemplo.com)")
    parser.add_argument(
        "--output", "-o", default="output",
        help="Pasta de saída (padrão: ./output)"
    )
    parser.add_argument(
        "--json-only", action="store_true",
        help="Imprime apenas o JSON no stdout, sem salvar arquivos"
    )
    args = parser.parse_args()

    url = args.url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    scraper = WebScraper(url)

    try:
        data = scraper.run()
    except requests.HTTPError as e:
        print(f"[ERRO] HTTP {e.response.status_code}: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.ConnectionError:
        print("[ERRO] Não foi possível conectar ao site.", file=sys.stderr)
        sys.exit(1)
    except requests.Timeout:
        print("[ERRO] Timeout ao tentar acessar o site.", file=sys.stderr)
        sys.exit(1)

    if args.json_only:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    scraper.save(args.output)

    # Resumo no terminal
    print("\n" + "─" * 50)
    print("RESUMO")
    print("─" * 50)
    print(f"  Título        : {data['html']['title']}")
    print(f"  Framework     : {data['react']['framework']}")
    print(f"  Tailwind      : {'Sim' if data['tailwind']['detected'] else 'Não'} "
          f"({data['tailwind']['unique_tw_classes']} classes únicas)")
    print(f"  CSS externo   : {len(data['css']['external_stylesheets'])} folhas")
    print(f"  Var. CSS      : {len(data['css']['css_variables'])}")
    print(f"  Links         : {data['html']['links_total']}")
    print(f"  Imagens       : {data['html']['images_total']}")
    print("─" * 50)


if __name__ == "__main__":
    main()
