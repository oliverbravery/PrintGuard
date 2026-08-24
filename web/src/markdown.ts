import DOMPurify from "dompurify";
import { marked } from "marked";

function resolved(raw: string | null, base: string | undefined): string | null {
  if (!raw || !base) return raw;
  try {
    return new URL(raw, base).href;
  } catch {
    return null;
  }
}

export function renderMarkdown(markdown: string, options: { base?: string; dropTitle?: boolean; skip?: string[] } = {}): string {
  const { base, dropTitle, skip = [] } = options;
  const html = DOMPurify.sanitize(marked.parse(markdown, { async: false }) as string, { FORBID_TAGS: ["style"] });
  const box = document.createElement("template");
  box.innerHTML = html;
  if (dropTitle) box.content.querySelector("h1")?.remove();
  for (const image of box.content.querySelectorAll("img")) {
    const src = resolved(image.getAttribute("src"), base);
    if (src && skip.some((known) => src.endsWith(`/${known}`))) {
      image.remove();
    } else if (src) {
      image.src = src;
      image.loading = "lazy";
    } else {
      image.remove();
    }
  }
  for (const anchor of box.content.querySelectorAll("a")) {
    const href = resolved(anchor.getAttribute("href"), base);
    if (href) anchor.href = href;
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
  }
  return box.innerHTML;
}
