import MarkdownIt from 'markdown-it'

let md: MarkdownIt | null = null

export function useMarkdown () {
  md ??= new MarkdownIt({ html: false, linkify: true })

  function renderMarkdown (text: string): string {
    return md!.render(text)
  }

  return { renderMarkdown }
}
