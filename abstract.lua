function Div(el)
  if el.classes:includes("abstract") then
    if FORMAT:match("latex") then
      local blocks = {}
      table.insert(blocks, pandoc.RawBlock("latex", "\\begin{abstract}"))
      for _, b in ipairs(el.content) do table.insert(blocks, b) end
      table.insert(blocks, pandoc.RawBlock("latex", "\\end{abstract}"))
      return blocks
    end
  end
end
