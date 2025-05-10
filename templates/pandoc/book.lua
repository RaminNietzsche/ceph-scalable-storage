-- Pandoc Lua filter for the book's fenced divs (HTML, EPUB, DOCX outputs).
-- * callouts (.tip .warn .note .try .deep .debug .box .summary .signature)
--   get a bold label paragraph and, for DOCX, a custom paragraph style;
-- * .algo divs (empty in the source) are expanded from their attributes.
local labels = {}

function Meta(m)
  if m.ui_labels then
    for k, v in pairs(m.ui_labels) do labels[k] = pandoc.utils.stringify(v) end
  end
  return m
end

local callout = { tip = true, warn = true, note = true, try = true, deep = true, debug = true }

local function label_para(text)
  return pandoc.Para({ pandoc.Strong({ pandoc.Str(text) }) })
end

function Div(el)
  local cls = el.classes[1]
  if not cls then return nil end
  if cls == 'algo' then
    local a = el.attributes
    local blocks = {
      label_para((labels.algorithm or 'Algorithm') .. ': ' .. (a.title or '')),
      pandoc.Para({ pandoc.Str((labels.algo_src or 'Source') .. ': '), pandoc.Code(a.src or '') }),
      pandoc.Para({ pandoc.Str((labels.algo_complexity or 'Complexity') .. ': ' .. (a.complexity or '')) }),
    }
    el.content = blocks
    el.attributes = {}
    el.attributes['custom-style'] = 'Algorithm'
    return el
  end
  if callout[cls] then
    table.insert(el.content, 1, label_para(labels[cls] or cls))
    el.attributes['custom-style'] = 'Callout ' .. cls
    return el
  end
  if cls == 'summary' and el.attributes.title then
    table.insert(el.content, 1, label_para(el.attributes.title))
    el.attributes.title = nil
    el.attributes['custom-style'] = 'Summary'
    return el
  end
  return nil
end
