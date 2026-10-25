-- Keep links useful when a Typst PDF is downloaded outside the website.
function Pandoc(doc)
  if FORMAT ~= "typst" then return doc end
  local base = pandoc.utils.stringify(doc.meta["pdf-link-base"] or "")
  local origin, prefix = base:match("^(https?://[^/]+)(/.*)$")
  if not origin then return doc end
  return doc:walk({
    Link = function(link)
      local target = link.target
      if target:match("^#") or target:match("^[%a][%w+.-]*:")
          or target:match("^//") then return link end
      local path = target:sub(1, 1) == "/" and target or prefix .. target
      local parts = {}
      for part in path:gmatch("[^/]+") do
        if part == ".." then table.remove(parts)
        elseif part ~= "." then table.insert(parts, part) end
      end
      link.target = origin .. "/" .. table.concat(parts, "/")
      return link
    end
  })
end
