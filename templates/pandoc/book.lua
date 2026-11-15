-- Pandoc Lua filter for the book's fenced divs (HTML, EPUB, DOCX outputs).
-- * callouts (.tip .warn .note .try .deep .debug .box .summary .signature)
--   get a bold label paragraph and, for DOCX, a custom paragraph style;
-- * .algo divs (empty in the source) are expanded from their attributes;
-- * .sim divs (empty) become a pointer to the web edition's interactive lab;
-- * .tldr (the chapter-opening TL;DR) becomes <details open> in HTML/EPUB.
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
  if cls == 'sim' then
    -- an interactive simulator of the web edition: a one-line pointer in the other formats
    local t = labels[(el.attributes.name or '') .. '_t'] or el.attributes.name or ''
    local s = (labels.sim_print or '{t}'):gsub('{t}', function() return t end)
    el.content = { pandoc.Para({ pandoc.Emph({ pandoc.Str(s) }) }) }
    el.attributes = {}
    el.attributes['custom-style'] = 'Callout note'
    return el
  end
  if callout[cls] then
    table.insert(el.content, 1, label_para(labels[cls] or cls))
    el.attributes['custom-style'] = 'Callout ' .. cls
    return el
  end
  if cls == 'tldr' then
    -- the chapter-opening TL;DR: <details open> in HTML and EPUB, a styled callout in DOCX
    local t = (labels.tldr_title or 'TL;DR') .. ' · ' .. (labels.tldr_sub or '')
    if FORMAT:match('html') or FORMAT:match('epub') then
      local out = { pandoc.RawBlock('html', '<details class="tldr" open="open"><summary>' .. t .. '</summary>') }
      for _, b in ipairs(el.content) do table.insert(out, b) end
      table.insert(out, pandoc.RawBlock('html', '</details>'))
      return out
    end
    table.insert(el.content, 1, label_para(t))
    el.attributes['custom-style'] = 'Summary'
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

-- Command blocks carry their Ceph release label (since="squid", from tools/export_pandoc.py):
-- a small line above the block, "Squid+ — Works on Ceph Squid (19.2) and later".
function CodeBlock(el)
  local lab = el.attributes['since-label']
  if not lab then return nil end
  local tt = el.attributes['since-title'] or ''
  el.attributes['since-label'] = nil
  el.attributes['since-title'] = nil
  local para = pandoc.Para({ pandoc.Strong({ pandoc.Str(lab) }), pandoc.Space(), pandoc.Str('—'), pandoc.Space(), pandoc.Emph({ pandoc.Str(tt) }) })
  local div = pandoc.Div({ para }, pandoc.Attr('', { 'since', 'since-' .. (el.attributes.since or '') }, { ['custom-style'] = 'Release label' }))
  return { div, el }
end

-- Meta must run before Div (pandoc otherwise visits block elements before the metadata)
return { { Meta = Meta }, { Div = Div, CodeBlock = CodeBlock } }
