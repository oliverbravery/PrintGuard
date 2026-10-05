import DOMPurify from "dompurify";
import { marked } from "marked";

const SANITISER = {
  ALLOWED_TAGS: [
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr", "ul", "ol", "li", "blockquote", "pre", "code",
    "strong", "em", "del", "a", "img", "table", "thead", "tbody", "tr", "th", "td",
  ],
  ALLOWED_ATTR: ["href", "src", "alt", "title", "align", "start", "width", "height"],
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
};

function resolved(raw: string | null, base: string | undefined): string | null {
  if (!raw || !base) return raw;
  try {
    return new URL(raw, base).href;
  } catch {
    return null;
  }
}

export function fromBase64(data: string): string {
  return new TextDecoder().decode(Uint8Array.from(atob(data), (c) => c.charCodeAt(0)));
}

export function renderMarkdown(
  markdown: string,
  options: { base?: string; dropTitle?: boolean; skip?: string[]; sources?: Record<string, string> } = {},
): string {
  const { base, dropTitle, skip = [], sources = {} } = options;
  const html = DOMPurify.sanitize(marked.parse(markdown, { async: false }) as string, SANITISER);
  const box = document.createElement("template");
  box.innerHTML = html;
  if (dropTitle) box.content.querySelector("h1")?.remove();
  for (const image of box.content.querySelectorAll("img")) {
    const raw = image.getAttribute("src") ?? "";
    const src = sources[raw] ?? resolved(raw, base);
    if (skip.includes(raw) || (src && skip.some((known) => src.endsWith(`/${known}`)))) {
      image.remove();
    } else if (src) {
      image.setAttribute("src", src);
      image.setAttribute("loading", "lazy");
    } else {
      image.remove();
    }
  }
  for (const anchor of box.content.querySelectorAll("a")) {
    const href = resolved(anchor.getAttribute("href"), base);
    if (href) anchor.setAttribute("href", href);
    anchor.setAttribute("target", "_blank");
    anchor.setAttribute("rel", "noreferrer");
  }
  return box.innerHTML;
}
