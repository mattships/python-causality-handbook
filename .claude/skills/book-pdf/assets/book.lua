--[[
book.lua -- pandoc filter that renders one chapter for the book design.

book.py has already normalised the chapter (heading levels, identifiers,
links, images, code-block languages, admonitions); this filter decides how
each element is set in LaTeX.

Metadata (set by book.py with -M):
  index_terms_file   Lua file returning the index terms (optional)
  chapter_id         this chapter's slug (index "home" ranges use it)
  keep_lines         listings shorter than this never split across pages

In order:
  1. Index marks, and links: running-text links keep their wording and get
     the URL as a footnote; inside reference lists (Div.book-refs) the URL
     follows the text instead.  Headings lose links and notes.
  2. Blocks: standalone images become centred, non-floating graphics (with
     a caption when the source gave one); listings get the code box, outputs
     the output style; tables get the table style; admonitions, API entries
     and missing images their boxes; a horizontal rule becomes a dinkus.
  3. Display maths alone in its paragraph is folded into the preceding
     paragraph, so TeX spaces it like hand-written LaTeX.
  4. Display maths goes through \fitmath; inline code gets break points.
]]

local stringify = pandoc.utils.stringify

local chapter_id = 'chapter'
local keep_lines = 14
local textwidth_pt = 379
local index_terms = {}

------------------------------------------------------------------------
-- helpers
------------------------------------------------------------------------

local function latex(s) return pandoc.RawInline('latex', s) end
local function latex_block(s) return pandoc.RawBlock('latex', s) end

local function to_latex_inlines(inlines)
  local doc = pandoc.Pandoc({pandoc.Plain(inlines)})
  return (pandoc.write(doc, 'latex'):gsub('%s+$', ''))
end

-- Escape text for use inside \texttt and similar.
local tt_escapes = {
  ['\\'] = '\\textbackslash{}', ['{'] = '\\{', ['}'] = '\\}',
  ['$'] = '\\$', ['&'] = '\\&', ['#'] = '\\#', ['^'] = '\\^{}',
  ['_'] = '\\_', ['%'] = '\\%', ['~'] = '\\textasciitilde{}',
  ['`'] = '\\textasciigrave{}',
}

-- Inline code: escaped, with discretionary breaks after punctuation that
-- commonly joins identifiers, so long names do not run into the margin.
local function tt_text(text)
  local out = {}
  for _, cp in utf8.codes(text) do
    local ch = utf8.char(cp)
    out[#out + 1] = tt_escapes[ch] or ch
    if ch == '_' or ch == '.' or ch == ',' or ch == '/' or ch == '(' or ch == '=' then
      out[#out + 1] = '\\codebreak{}'
    end
  end
  return table.concat(out)
end

local function inline_code(text) return '\\code{' .. tt_text(text) .. '}' end

-- Plain text for a LaTeX argument (aside labels, missing-image notes).
local function tex_text(s)
  return (s:gsub('[\\{}$&#^_%%~]', function(c) return tt_escapes[c] end))
end

------------------------------------------------------------------------
-- 1a. index
------------------------------------------------------------------------

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

-- Outside its home chapters a term is indexed at its first mention.
local index_state = {home = {}, count = {}, seen = {}}

local function index_inlines(inlines)
  local parts, starts, pos = {}, {}, 1
  for i, il in ipairs(inlines) do
    local t = (il.t == 'Str' or il.t == 'Code') and il.text or ' '
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
        inserts[#inserts + 1] = {at, '\\index{' .. (term.key or index_key(e)) .. '}'}
        index_state.seen[e] = true
        index_state.count[e] = (index_state.count[e] or 0) + 1
      end
    end
  end
  table.sort(inserts, function(a, b) return a[1] > b[1] end)
  for _, ins in ipairs(inserts) do inlines:insert(ins[1], latex(ins[2])) end
  return inlines
end

------------------------------------------------------------------------
-- 1b. links
------------------------------------------------------------------------

local function is_external(url)
  return url:match('^https?://') or url:match('^ftp://') or url:match('^mailto:')
end

local function same_as_url(text, url)
  local norm = function(s) return (s:gsub('^https?://', ''):gsub('^mailto:', ''):gsub('/$', '')) end
  return norm(text) == norm(url)
end

-- Link -> text + footnote carrying the URL.
local function link_with_note(el)
  if not is_external(el.target) then return el end
  if same_as_url(stringify(el.content), el.target) then
    return pandoc.Link({pandoc.Str(stringify(el.content))}, el.target)
  end
  local url = pandoc.Link({pandoc.Str(el.target:gsub('^mailto:', ''))}, el.target)
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

local function link_to_text(el) return el.content end

local function walk_links(blk)
  if blk.t == 'Header' then
    return pandoc.walk_block(blk, {Link = link_to_text, Note = function() return {} end})
  end
  if blk.t == 'Div' and blk.classes:includes('book-refs') then
    return pandoc.walk_block(blk, {Link = link_with_inline_url}).content
  end
  index_state.seen = {}
  blk = pandoc.walk_block(blk, {Inlines = index_inlines})
  return pandoc.walk_block(blk, {Link = link_with_note})
end

local function document(doc)
  local m = doc.meta
  if m.chapter_id then chapter_id = stringify(m.chapter_id) end
  if m.keep_lines then keep_lines = tonumber(stringify(m.keep_lines)) or keep_lines end
  if m.textwidth_pt then textwidth_pt = tonumber(stringify(m.textwidth_pt)) or textwidth_pt end
  if m.index_terms_file then index_terms = dofile(stringify(m.index_terms_file)) end

  local opens, closes = {}, {}
  for _, term in ipairs(index_terms) do
    for _, h in ipairs(term.home or {}) do
      if h == chapter_id then
        index_state.home[term.entry] = true
        local key = term.key or index_key(term.entry)
        opens[#opens + 1] = '\\index{' .. key .. '|(}'
        closes[#closes + 1] = '\\index{' .. key .. '|)}'
      end
    end
  end

  local out = pandoc.List()
  if #opens > 0 then out:insert(latex_block(table.concat(opens, '\n'))) end
  for _, blk in ipairs(doc.blocks) do
    local res = walk_links(blk)
    if res.t then out:insert(res) else out:extend(res) end
  end
  if #closes > 0 then out:insert(latex_block(table.concat(closes, '\n'))) end
  doc.blocks = out
  return doc
end

------------------------------------------------------------------------
-- 2. blocks
------------------------------------------------------------------------

-- A figure with an identifier is numbered (Figure 3.2) and can be referred
-- to; one without is captioned, or not, as the source wishes.
local function image_block(img, caption, ident)
  local w = img.attributes.width or '0.8\\linewidth'
  local h = img.attributes.height or '0.4\\textheight'
  local res = pandoc.List({latex_block('\\bookimage{' .. w .. '}{' .. h .. '}{' .. img.src .. '}')})
  ident = ident or ''
  if ident ~= '' or (caption and #caption > 0) then
    local opt = ident ~= '' and ('[' .. ident .. ']') or ''
    res:insert(latex_block('\\bookcaption' .. opt .. '{' .. to_latex_inlines(caption or {}) .. '}'))
  end
  return res
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

local function caption_of(img)
  local c = img.attributes['book-caption']
  if c == 'yes' then return img.caption end
  return nil
end

-- A table without column widths is set at its natural width; when that is
-- wider than the text, give the columns relative widths (pandoc then sets
-- them as wrapping p-columns), in proportion to their longest cells.
local function fit_table(el)
  for _, cs in ipairs(el.colspecs) do
    if type(cs[2]) == 'number' and cs[2] > 0 then return end
  end
  local n = #el.colspecs
  local maxlen = {}
  for i = 1, n do maxlen[i] = 1 end
  local function scan(rows)
    for _, row in ipairs(rows) do
      local col = 1
      for _, cell in ipairs(row.cells) do
        local span = cell.col_span or 1
        if span == 1 and col <= n then
          local s = stringify(cell.contents)
          local l = utf8.len(s) or #s
          if l > maxlen[col] then maxlen[col] = l end
        end
        col = col + span
      end
    end
  end
  scan(el.head.rows)
  for _, body in ipairs(el.bodies) do scan(body.head) scan(body.body) end
  scan(el.foot.rows)
  local total = 0
  for _, l in ipairs(maxlen) do total = total + l end
  -- \small table text runs about 4.6pt a character; 12pt of padding a column
  if total * 4.6 + 12 * n <= textwidth_pt then return end
  local weights, sum = {}, 0
  for i, l in ipairs(maxlen) do
    weights[i] = math.max(math.min(l, 60), 6)
    sum = sum + weights[i]
  end
  for i, cs in ipairs(el.colspecs) do
    el.colspecs[i] = {cs[1], 0.98 * weights[i] / sum}
  end
end

-- Figures first: their images must not be taken for standalone ones.
local figures_filter = {
  Figure = function(el)
    local img = nil
    pandoc.walk_block(el, {Image = function(i) img = img or i end})
    if img then
      local cap = el.caption and el.caption.long and el.caption.long[1]
      local inl = cap and cap.content or nil
      if inl and #inl == 0 then inl = nil end
      local ident = el.identifier ~= '' and el.identifier or img.identifier
      return image_block(img, inl or caption_of(img), ident)
    end
  end,
}

-- Columns of numbers are right-aligned when the source did not say
-- (Word tables lose their alignment in pandoc; Markdown often omits it).
local function align_numbers(el)
  local n = #el.colspecs
  local numeric, seen = {}, {}
  for i = 1, n do numeric[i] = true end
  for _, body in ipairs(el.bodies) do
    for _, row in ipairs(body.body) do
      local col = 1
      for _, cell in ipairs(row.cells) do
        local s = stringify(cell.contents):gsub('^%s+', ''):gsub('%s+$', '')
        if s ~= '' and col <= n then
          seen[col] = true
          if not (s:match('^[%-+]?%d[%d.,]*%%?$') or s:match('^[%-+]?%.%d+%%?$')) then
            numeric[col] = false
          end
        end
        col = col + (cell.col_span or 1)
      end
    end
  end
  for i, cs in ipairs(el.colspecs) do
    if numeric[i] and seen[i] and tostring(cs[1]) == 'AlignDefault' then
      el.colspecs[i] = {pandoc.AlignRight, cs[2]}
    end
  end
end

local blocks_filter = {
  Para = function(el)
    local img = only_image(el.content)
    if img then return image_block(img, caption_of(img), img.identifier) end
  end,

  Plain = function(el)
    local img = only_image(el.content)
    if img then return image_block(img, caption_of(img), img.identifier) end
  end,

  -- Listings and outputs of up to keep_lines lines are not split across
  -- pages.  book.py has set the first class to a language pandoc can
  -- highlight, or to "plain".
  CodeBlock = function(el)
    local short = select(2, el.text:gsub('\n', '')) < keep_lines
    if el.classes:includes('output') then
      local opt = short and '[samepage=true]' or ''
      return latex_block('\\begin{pyout}' .. opt .. '\n' .. el.text .. '\n\\end{pyout}')
    end
    if el.classes[1] == 'plain' or #el.classes == 0 then
      local box = short and 'codeboxkeep' or 'codebox'
      return latex_block('\\begin{' .. box .. '}\n\\begin{plaincode}\n' .. el.text ..
                         '\n\\end{plaincode}\n\\end{' .. box .. '}')
    end
    local res = pandoc.List()
    if short then res:insert(latex_block('\\keepnextcode')) end
    if el.classes:includes('numberLines') then res:insert(latex_block('\\numbernextcode')) end
    res:insert(el)
    return res
  end,

  Table = function(el)
    fit_table(el)
    align_numbers(el)
    -- a caption without an identifier is not numbered
    local pre = nil
    local cap = el.caption and el.caption.long
    if el.identifier == '' and cap and #cap > 0 then
      pre = latex_block('\\booktablecaption{' .. to_latex_inlines(pandoc.utils.blocks_to_inlines(cap)) .. '}')
      el.caption.long = pandoc.Blocks({})
    end
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
    local res = pandoc.List({latex_block('\\begin{mdtable}')})
    if pre then res:insert(pre) end
    res:insert(el)
    res:insert(latex_block('\\end{mdtable}'))
    return res
  end,

  HorizontalRule = function() return latex_block('\\bookbreak') end,

  Div = function(el)
    if el.classes:includes('admonition') then
      local label = el.attributes.label or 'Note'
      local res = pandoc.List({latex_block('\\begin{bookaside}{' .. tex_text(label) .. '}')})
      res:extend(el.content)
      res:insert(latex_block('\\end{bookaside}'))
      return res
    end
    if el.classes:includes('bookapi') then
      local sig = el.attributes.signature or ''
      local mark = ''
      if el.attributes.index and el.attributes.index ~= '' then
        mark = '\\index{' .. el.attributes.index .. '}'
      end
      local res = pandoc.List({latex_block('\\begin{bookapi}{' .. tt_text(sig) .. '}' .. mark)})
      res:extend(el.content)
      res:insert(latex_block('\\end{bookapi}'))
      return res
    end
    if el.classes:includes('missing-image') then
      return latex_block('\\missingimage{' .. tex_text(stringify(el.content)) .. '}')
    end
  end,

  RawBlock = function(el)
    if el.format ~= 'latex' and el.format ~= 'tex' then return {} end
  end,
  RawInline = function(el)
    if el.format ~= 'latex' and el.format ~= 'tex' then return {} end
  end,
}

------------------------------------------------------------------------
-- 3. display maths
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
-- 4. inline code and maths (after folding, which looks for Math elements)
------------------------------------------------------------------------

-- Headings are left to pandoc, which writes \texttt and gives the PDF
-- bookmark a plain-text version of the title.
local inlines_filter = {
  traverse = 'topdown',
  Header = function(el) return el, false end,
  Code = function(el) return latex(inline_code(el.text)) end,

  Math = function(el)
    if el.mathtype == 'DisplayMath' then
      -- labelled displays are numbered, as LaTeX numbers them
      if el.text:find('\\label{', 1, true) or el.text:find('\\tag{', 1, true) then
        local t = el.text
        if t:match('^%s*\\begin{aligned}') then
          t = t:gsub('\\begin{aligned}', '\\begin{align}'):gsub('\\end{aligned}', '\\end{align}')
          return latex(t)
        elseif t:match('^%s*\\begin{gathered}') then
          t = t:gsub('\\begin{gathered}', '\\begin{gather}'):gsub('\\end{gathered}', '\\end{gather}')
          return latex(t)
        end
        return latex('\\begin{equation}' .. t .. '\\end{equation}')
      end
      return latex('\\[\\fitmath{' .. el.text .. '}\\]')
    end
    -- let long inline formulas break after a comma-space, like prose
    if el.text:find(', ') then
      return latex('\\(' .. el.text:gsub(', ', ',\\allowbreak ') .. '\\)')
    end
  end,
}

return {
  {Pandoc = document},
  figures_filter,
  blocks_filter,
  {Blocks = fold_displays},
  inlines_filter,
}
