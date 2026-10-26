--[[
book.lua -- pandoc filter that adapts one converted notebook for print.

Expected metadata (set by build.py with -M):
  chapter_id        prefix that makes heading identifiers unique in the book
  keep_contribute   "true" to keep a "Contribute" section (the preface does)

What it does, in order:
  1. Structure: notebook "##" headings become \section, "###" \subsection,
     and so on (the "#" title is typeset by the chapter opener, so any later
     "#" heading is treated as a section).  The "Contribute" appeal that
     closes every chapter is dropped, since it appears once in the preface.
  2. Links: body-text links keep their text and get the URL as a footnote.
     Inside "References" sections the URL is printed inline instead.
  3. Blocks: standalone images become centred, non-floating graphics; code
     blocks with the class "output" become the `pyout` environment; pipe
     tables are wrapped in `mdtable`; horizontal rules become a dinkus.
  4. Display maths that sits alone in its own paragraph is folded into the
     preceding paragraph (and a lowercase continuation such as "where ..."
     is pulled up after it), so TeX spaces it like hand-written LaTeX.
  5. Display maths goes through \fitmath (which shrinks the rare equation
     wider than the page); inline code gets break points.
]]

local stringify = pandoc.utils.stringify

local chapter_id = 'chapter'
local keep_contribute = false

------------------------------------------------------------------------
-- helpers
------------------------------------------------------------------------

local function latex(s) return pandoc.RawInline('latex', s) end
local function latex_block(s) return pandoc.RawBlock('latex', s) end

-- Escape text for use inside \texttt and similar.
local tt_escapes = {
  ['\\'] = '\\textbackslash{}', ['{'] = '\\{', ['}'] = '\\}',
  ['$'] = '\\$', ['&'] = '\\&', ['#'] = '\\#', ['^'] = '\\^{}',
  ['_'] = '\\_', ['%'] = '\\%', ['~'] = '\\textasciitilde{}',
  ['`'] = '\\textasciigrave{}',
}

-- Inline code: escaped, with discretionary breaks after punctuation that
-- commonly joins identifiers, so long names do not run into the margin.
local function inline_code(text)
  local out = {}
  for _, cp in utf8.codes(text) do
    local ch = utf8.char(cp)
    out[#out + 1] = tt_escapes[ch] or ch
    if ch == '_' or ch == '.' or ch == ',' or ch == '/' or ch == '(' or ch == '=' then
      out[#out + 1] = '\\codebreak{}'
    end
  end
  return '\\code{' .. table.concat(out) .. '}'
end

local function heading_text(h) return stringify(h.content) end

------------------------------------------------------------------------
-- index
------------------------------------------------------------------------

local here = (PANDOC_SCRIPT_FILE or ''):match('(.*/)') or './'
local index_terms = dofile(here .. 'index_terms.lua')

-- makeindex string with lowercase sort keys at every level.
local function index_key(entry)
  local levels = {}
  for level in (entry .. '!'):gmatch('([^!]*)!') do
    if not level:find('@', 1, true) then
      level = level:lower():gsub('%s*%(.-%)', '') .. '@' .. level
    end
    levels[#levels + 1] = level
  end
  return table.concat(levels, '!')
end

local function is_word(c) return c ~= nil and c ~= '' and c:match('[%w]') ~= nil end

-- Positions (1-based, in `text`) where a term starts.
local function find_term(term, text, lower)
  local hits = {}
  for _, pat in ipairs(term.patterns or {}) do
    local from = 1
    while true do
      local s, e = lower:find(pat, from, true)
      if not s then break end
      if not is_word(lower:sub(s - 1, s - 1)) then hits[#hits + 1] = {s, e} end
      from = s + 1
    end
  end
  for _, acr in ipairs(term.acronyms or {}) do
    local from = 1
    while true do
      local s, e = text:find(acr, from, true)
      if not s then break end
      if not is_word(text:sub(s - 1, s - 1)) and not is_word(text:sub(e + 1, e + 1)) then
        hits[#hits + 1] = {s, e}
      end
      from = s + 1
    end
  end
  -- drop matches that are part of a phrase indexed elsewhere
  local keep = {}
  for _, h in ipairs(hits) do
    local excluded = false
    for _, ex in ipairs(term.exclude or {}) do
      local from = 1
      while not excluded do
        local s, e = lower:find(ex, from, true)
        if not s then break end
        if s <= h[1] and e >= h[2] then excluded = true end
        from = s + 1
      end
    end
    if not excluded then keep[#keep + 1] = h end
  end
  table.sort(keep, function(a, b) return a[1] < b[1] end)
  return keep
end

local index_state = {home = {}, count = {}, seen = {}}

local function index_inlines(inlines)
  -- the list's text, with the starting offset of every Str
  local parts, starts, pos = {}, {}, 1
  for i, il in ipairs(inlines) do
    local t = il.t == 'Str' and il.text or ' '
    starts[#starts + 1] = {pos, i}
    parts[#parts + 1] = t
    pos = pos + #t
  end
  local text = table.concat(parts)
  local lower = text:lower()
  local inserts = {}
  for _, term in ipairs(index_terms) do
    local e = term.entry
    if not index_state.home[e] and not index_state.seen[e]
        and (index_state.count[e] or 0) < 1 then
      local hit = find_term(term, text, lower)[1]
      if hit then
        local at = 1
        for _, st in ipairs(starts) do
          if st[1] <= hit[1] then at = st[2] else break end
        end
        inserts[#inserts + 1] = {at, '\\index{' .. index_key(e) .. '}'}
        index_state.seen[e] = true
        index_state.count[e] = (index_state.count[e] or 0) + 1
      end
    end
  end
  table.sort(inserts, function(a, b) return a[1] > b[1] end)
  for _, ins in ipairs(inserts) do
    inlines:insert(ins[1], latex(ins[2]))
  end
  return inlines
end

------------------------------------------------------------------------
-- 2. links
------------------------------------------------------------------------

local function is_external(url)
  return url:match('^https?://') or url:match('^ftp://') or url:match('^mailto:')
end

local function same_as_url(text, url)
  local norm = function(s) return (s:gsub('^https?://', ''):gsub('/$', '')) end
  return norm(text) == norm(url)
end

-- Link -> text + footnote carrying the URL.
local function link_with_note(el)
  if not is_external(el.target) then return el end
  if same_as_url(stringify(el.content), el.target) then
    return pandoc.Link({pandoc.Str(el.target)}, el.target)
  end
  local url = pandoc.Link({pandoc.Str(el.target)}, el.target)
  return {el, pandoc.Note({pandoc.Plain({url})})}
end

-- Link -> text + the URL in small type right after it (reference lists).
local function link_with_inline_url(el)
  if not is_external(el.target) then return el end
  if same_as_url(stringify(el.content), el.target) then
    return {latex('{\\refurlfont '), pandoc.Link({pandoc.Str(el.target)}, el.target), latex('}')}
  end
  return {el, latex('\\refurl{'), pandoc.Link({pandoc.Str(el.target)}, el.target), latex('}')}
end

-- Headings must not get footnotes: keep the text only.
local function link_to_text(el) return el.content end

------------------------------------------------------------------------
-- 1. structure (runs on the whole document, in reading order)
------------------------------------------------------------------------

local function new_level(level)
  if level <= 2 then return 1 end
  return level - 1
end

local function structure(doc)
  if doc.meta.chapter_id then chapter_id = stringify(doc.meta.chapter_id) end
  if doc.meta.keep_contribute then
    keep_contribute = stringify(doc.meta.keep_contribute) == 'true'
  end

  local opens, closes = {}, {}
  for _, term in ipairs(index_terms) do
    for _, h in ipairs(term.home or {}) do
      if h == chapter_id then
        index_state.home[term.entry] = true
        opens[#opens + 1] = '\\index{' .. index_key(term.entry) .. '|(}'
        closes[#closes + 1] = '\\index{' .. index_key(term.entry) .. '|)}'
      end
    end
  end

  local out = pandoc.List()
  if #opens > 0 then out:insert(latex_block(table.concat(opens, '\n'))) end
  local drop_level = nil       -- dropping a "Contribute" section of this level
  local refs_level = nil       -- inside a "References" section of this level
  local used_ids = {}
  local seq = 0

  for _, blk in ipairs(doc.blocks) do
    if blk.t == 'Header' then
      local text = heading_text(blk)
      if drop_level and blk.level <= drop_level then drop_level = nil end
      if refs_level and blk.level <= refs_level then refs_level = nil end

      if not keep_contribute and text:match('^%s*Contribute') then
        drop_level = blk.level
      elseif not drop_level then
        if text:match('^%s*References?%s*$') then refs_level = blk.level end
        blk.level = new_level(blk.level)
        seq = seq + 1
        local ident = blk.identifier ~= '' and blk.identifier or ('sec' .. seq)
        ident = chapter_id .. '-' .. ident
        while used_ids[ident] do ident = ident .. '-x' end
        used_ids[ident] = true
        blk.identifier = ident
        if chapter_id == 'preface' then        -- keep the preface's sections out of the TOC
          blk.classes:extend({'unnumbered', 'unlisted'})
        end
        blk = pandoc.walk_block(blk, {Link = link_to_text, Note = function() return {} end})
        out:insert(blk)
      end
    elseif not drop_level then
      if refs_level then
        out:insert(pandoc.walk_block(blk, {Link = link_with_inline_url}))
      else
        index_state.seen = {}
        blk = pandoc.walk_block(blk, {Inlines = index_inlines})
        out:insert(pandoc.walk_block(blk, {Link = link_with_note}))
      end
    end
  end
  if #closes > 0 then out:insert(latex_block(table.concat(closes, '\n'))) end
  doc.blocks = out
  return doc
end

------------------------------------------------------------------------
-- 3. blocks
------------------------------------------------------------------------

local function image_block(img)
  local w = img.attributes.width or '0.8\\linewidth'
  local h = img.attributes.height or '0.4\\textheight'
  return latex_block('\\bookimage{' .. w .. '}{' .. h .. '}{' .. img.src .. '}')
end

local function only_image(inlines)
  local img = nil
  for _, il in ipairs(inlines) do
    if il.t == 'Image' then
      if img then return nil end
      img = il
    elseif il.t ~= 'Space' and il.t ~= 'SoftBreak' and il.t ~= 'LineBreak' then
      return nil
    end
  end
  return img
end

local KEEP_LINES = 14

local blocks_filter = {
  Para = function(el)
    local img = only_image(el.content)
    if img then return image_block(img) end
  end,

  Plain = function(el)
    local img = only_image(el.content)
    if img then return image_block(img) end
  end,

  Figure = function(el)
    local img = nil
    pandoc.walk_block(el, {Image = function(i) img = img or i end})
    if img then return image_block(img) end
  end,

  -- Listings and outputs of up to KEEP_LINES lines are not split across pages.
  -- Python is highlighted by pandoc (the Shaded environment); a block with no
  -- language gets the same box, unhighlighted.
  CodeBlock = function(el)
    local short = select(2, el.text:gsub('\n', '')) < KEEP_LINES
    if el.classes:includes('output') then
      local opt = short and '[samepage=true]' or ''
      return latex_block('\\begin{pyout}' .. opt .. '\n' .. el.text .. '\n\\end{pyout}')
    end
    local lang = el.classes[1]
    if lang == 'python' or lang == 'python3' or lang == 'py' or lang == 'ipython' then
      el.classes = {'python'}
      if short then return {latex_block('\\keepnextcode'), el} end
      return el
    end
    local box = short and 'codeboxkeep' or 'codebox'
    return latex_block('\\begin{' .. box .. '}\n\\begin{plaincode}\n' .. el.text ..
                       '\n\\end{plaincode}\n\\end{' .. box .. '}')
  end,

  Table = function(el)
    -- header cells get the same weight as in data-frame tables
    for _, row in ipairs(el.head.rows) do
      for _, cell in ipairs(row.cells) do
        cell.contents = pandoc.walk_block(pandoc.Div(cell.contents), {
          Plain = function(p)
            p.content:insert(1, latex('\\dfh{'))
            p.content:insert(latex('}'))
            return p
          end,
        }).content
      end
    end
    return {latex_block('\\begin{mdtable}'), el, latex_block('\\end{mdtable}')}
  end,

  HorizontalRule = function() return latex_block('\\bookbreak') end,

  Div = function(el)
    if el.classes:includes('admonition') then
      local kind = el.attributes.kind or 'note'
      local label = kind:sub(1, 1):upper() .. kind:sub(2)
      local res = pandoc.List({latex_block('\\begin{bookaside}{' .. label .. '}')})
      res:extend(el.content)
      res:insert(latex_block('\\end{bookaside}'))
      return res
    end
  end,
}

------------------------------------------------------------------------
-- 4. display maths
------------------------------------------------------------------------

local function is_space(il)
  return il.t == 'Space' or il.t == 'SoftBreak' or il.t == 'LineBreak'
end

-- A paragraph that holds nothing but display maths.
local function display_only(blk)
  if blk.t ~= 'Para' then return false end
  local found = false
  for _, il in ipairs(blk.content) do
    if il.t == 'Math' and il.mathtype == 'DisplayMath' then
      found = true
    elseif not is_space(il) then
      return false
    end
  end
  return found
end

-- A raw amsmath display environment written as its own block.
local function raw_display(blk)
  return blk.t == 'RawBlock' and (blk.format == 'latex' or blk.format == 'tex')
    and blk.text:match('^%s*\\begin{(%a+)%*?}') ~= nil
    and (blk.text:match('^%s*\\begin{align') or blk.text:match('^%s*\\begin{gather')
         or blk.text:match('^%s*\\begin{multline') or blk.text:match('^%s*\\begin{equation'))
end

local function as_inlines(blk)
  if blk.t == 'Para' then return blk.content end
  return pandoc.Inlines({pandoc.RawInline('latex', blk.text)})
end

-- Text that continues the sentence the display interrupted ("where ...").
local function continues_sentence(blk)
  if not blk or blk.t ~= 'Para' or #blk.content == 0 then return false end
  local first = nil
  for _, il in ipairs(blk.content) do
    if not (il.t == 'RawInline' and il.text:match('^\\index{')) then first = il break end
  end
  return first ~= nil and first.t == 'Str'
    and (first.text:match('^%l') ~= nil or first.text:match('^[,.;:]') ~= nil)
end

-- Standalone display that has no paragraph to join: centre it without
-- letting TeX start an empty paragraph line above it.
local function standalone_display(blk)
  if blk.t ~= 'Para' then return blk end
  local res = pandoc.List()
  for _, il in ipairs(blk.content) do
    if il.t == 'Math' then
      res:insert(latex_block('\\begin{displaypara}\\fitmath{' .. il.text .. '}\\end{displaypara}'))
    end
  end
  return res
end

local function fold_displays(blocks)
  local out = pandoc.List()
  local i = 1
  while i <= #blocks do
    local blk = blocks[i]
    if display_only(blk) or raw_display(blk) then
      local prev = out[#out]
      if prev and prev.t == 'Para' then
        prev.content:insert(pandoc.SoftBreak())
        prev.content:extend(as_inlines(blk))
        if continues_sentence(blocks[i + 1]) then
          prev.content:insert(pandoc.SoftBreak())
          prev.content:extend(blocks[i + 1].content)
          i = i + 1
        end
      elseif display_only(blk) then
        out:extend(standalone_display(blk))
      else
        out:insert(blk)
      end
    else
      out:insert(blk)
    end
    i = i + 1
  end
  return out
end

------------------------------------------------------------------------
-- 5. inline code and maths (after folding, which looks for Math elements)
------------------------------------------------------------------------

local inlines_filter = {
  Code = function(el) return latex(inline_code(el.text)) end,

  Math = function(el)
    if el.mathtype == 'DisplayMath' then
      return latex('\\[\\fitmath{' .. el.text .. '}\\]')
    end
    -- let long inline formulas break after a comma-space, like prose
    if el.text:find(', ') then
      return latex('\\(' .. el.text:gsub(', ', ',\\allowbreak ') .. '\\)')
    end
  end,
}

return {
  {Pandoc = structure},
  blocks_filter,
  {Blocks = fold_displays},
  inlines_filter,
}
