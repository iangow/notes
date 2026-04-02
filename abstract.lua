function Div(el)
  if el.classes:includes("abstract") then
    if FORMAT:match("latex") then
      local blocks = {}
      table.insert(blocks, pandoc.RawBlock("latex", "\\begin{abstract}"))
      for _, b in ipairs(el.content) do table.insert(blocks, b) end
      table.insert(blocks, pandoc.RawBlock("latex", "\\end{abstract}"))
      return blocks
    elseif FORMAT:match("typst") then
      local blocks = pandoc.List()
      local content = el.content:clone()

      if #content > 0 and content[1].t == "Para" then
        local first = content[1]
        local inlines = pandoc.List()
        inlines:insert(pandoc.Strong({ pandoc.Str("Abstract.") }))
        inlines:insert(pandoc.Space())
        for _, inline in ipairs(first.content) do
          inlines:insert(inline)
        end
        content[1] = pandoc.Para(inlines)
        return content
      else
        blocks:insert(pandoc.Para({ pandoc.Strong({ pandoc.Str("Abstract.") }) }))
        for _, b in ipairs(content) do
          blocks:insert(b)
        end
        return blocks
      end
    end
  end
end
