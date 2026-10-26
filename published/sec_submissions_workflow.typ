// Simple numbering for non-book documents
#let equation-numbering = "(1)"
#let callout-numbering = "1"
#let subfloat-numbering(n-super, subfloat-idx) = {
  numbering("1a", n-super, subfloat-idx)
}

// Theorem configuration for theorion
// Simple numbering for non-book documents (no heading inheritance)
#let theorem-inherited-levels = 0

// Theorem numbering format (can be overridden by extensions for appendix support)
// This function returns the numbering pattern to use
#let theorem-numbering(loc) = "1.1"

// Default theorem render function
#let theorem-render(prefix: none, title: "", full-title: auto, body) = {
  if full-title != "" and full-title != auto and full-title != none {
    strong[#full-title.]
    h(0.5em)
  }
  body
}
// Some definitions presupposed by pandoc's typst output.
#let content-to-string(content) = {
  if content.has("text") {
    content.text
  } else if content.has("children") {
    content.children.map(content-to-string).join("")
  } else if content.has("body") {
    content-to-string(content.body)
  } else if content == [ ] {
    " "
  }
}

#let horizontalrule = line(start: (25%,0%), end: (75%,0%))

#let endnote(num, contents) = [
  #stack(dir: ltr, spacing: 3pt, super[#num], contents)
]

#show terms.item: it => block(breakable: false)[
  #text(weight: "bold")[#it.term]
  #block(inset: (left: 1.5em, top: -0.4em))[#it.description]
]

// Some quarto-specific definitions.

#show raw.where(block: true): set block(
    fill: luma(230),
    width: 100%,
    inset: 8pt,
    radius: 2pt
  )

#let block_with_new_content(old_block, new_content) = {
  let fields = old_block.fields()
  let _ = fields.remove("body")
  if fields.at("below", default: none) != none {
    // TODO: this is a hack because below is a "synthesized element"
    // according to the experts in the typst discord...
    fields.below = fields.below.abs
  }
  block.with(..fields)(new_content)
}

#let empty(v) = {
  if type(v) == str {
    // two dollar signs here because we're technically inside
    // a Pandoc template :grimace:
    v.matches(regex("^\\s*$")).at(0, default: none) != none
  } else if type(v) == content {
    if v.at("text", default: none) != none {
      return empty(v.text)
    }
    for child in v.at("children", default: ()) {
      if not empty(child) {
        return false
      }
    }
    return true
  }

}

// Subfloats
// This is a technique that we adapted from https://github.com/tingerrr/subpar/
#let quartosubfloatcounter = counter("quartosubfloatcounter")

#let quarto_super(
  kind: str,
  caption: none,
  label: none,
  supplement: str,
  position: none,
  subcapnumbering: "(a)",
  body,
) = {
  context {
    let figcounter = counter(figure.where(kind: kind))
    let n-super = figcounter.get().first() + 1
    set figure.caption(position: position)
    [#figure(
      kind: kind,
      supplement: supplement,
      caption: caption,
      {
        show figure.where(kind: kind): set figure(numbering: _ => {
          let subfloat-idx = quartosubfloatcounter.get().first() + 1
          subfloat-numbering(n-super, subfloat-idx)
        })
        show figure.where(kind: kind): set figure.caption(position: position)

        show figure: it => {
          let num = numbering(subcapnumbering, n-super, quartosubfloatcounter.get().first() + 1)
          show figure.caption: it => block({
            num.slice(2) // I don't understand why the numbering contains output that it really shouldn't, but this fixes it shrug?
            [ ]
            it.body
          })

          quartosubfloatcounter.step()
          it
          counter(figure.where(kind: it.kind)).update(n => n - 1)
        }

        quartosubfloatcounter.update(0)
        body
      }
    )#label]
  }
}

// callout rendering
// this is a figure show rule because callouts are crossreferenceable
#show figure: it => {
  if type(it.kind) != str {
    return it
  }
  let kind_match = it.kind.matches(regex("^quarto-callout-(.*)")).at(0, default: none)
  if kind_match == none {
    return it
  }
  let kind = kind_match.captures.at(0, default: "other")
  kind = upper(kind.first()) + kind.slice(1)
  // now we pull apart the callout and reassemble it with the crossref name and counter

  // when we cleanup pandoc's emitted code to avoid spaces this will have to change
  let old_callout = it.body.children.at(1).body.children.at(1)
  let old_title_block = old_callout.body.children.at(0)
  let children = old_title_block.body.body.children
  let old_title = if children.len() == 1 {
    children.at(0)  // no icon: title at index 0
  } else {
    children.at(1)  // with icon: title at index 1
  }

  // TODO use custom separator if available
  // Use the figure's counter display which handles chapter-based numbering
  // (when numbering is a function that includes the heading counter)
  let callout_num = it.counter.display(it.numbering)
  let new_title = if empty(old_title) {
    [#kind #callout_num]
  } else {
    [#kind #callout_num: #old_title]
  }

  let new_title_block = block_with_new_content(
    old_title_block,
    block_with_new_content(
      old_title_block.body,
      if children.len() == 1 {
        new_title  // no icon: just the title
      } else {
        children.at(0) + new_title  // with icon: preserve icon block + new title
      }))

  align(left, block_with_new_content(old_callout,
    block(below: 0pt, new_title_block) +
    old_callout.body.children.at(1)))
}

// 2023-10-09: #fa-icon("fa-info") is not working, so we'll eval "#fa-info()" instead
#let callout(body: [], title: "Callout", background_color: rgb("#dddddd"), icon: none, icon_color: black, body_background_color: white) = {
  block(
    breakable: false, 
    fill: background_color, 
    stroke: (paint: icon_color, thickness: 0.5pt, cap: "round"), 
    width: 100%, 
    radius: 2pt,
    block(
      inset: 1pt,
      width: 100%, 
      below: 0pt, 
      block(
        fill: background_color,
        width: 100%,
        inset: 8pt)[#if icon != none [#text(icon_color, weight: 900)[#icon] ]#title]) +
      if(body != []){
        block(
          inset: 1pt, 
          width: 100%, 
          block(fill: body_background_color, width: 100%, inset: 8pt, body))
      }
    )
}


// syntax highlighting functions from skylighting:
/* Function definitions for syntax highlighting generated by skylighting: */
#let EndLine() = raw("\n")
#let Skylighting(fill: none, number: false, start: 1, sourcelines) = {
   let blocks = []
   let lnum = start - 1
   let bgcolor = rgb("#f1f3f5")
   for ln in sourcelines {
     if number {
       lnum = lnum + 1
       blocks = blocks + box(width: if start + sourcelines.len() > 999 { 30pt } else { 24pt }, text(fill: rgb("#aaaaaa"), [ #lnum ]))
     }
     blocks = blocks + ln + EndLine()
   }
   block(fill: bgcolor, width: 100%, inset: 8pt, radius: 2pt, blocks)
}
#let AlertTok(s) = text(fill: rgb("#ad0000"),raw(s))
#let AnnotationTok(s) = text(fill: rgb("#5e5e5e"),raw(s))
#let AttributeTok(s) = text(fill: rgb("#657422"),raw(s))
#let BaseNTok(s) = text(fill: rgb("#ad0000"),raw(s))
#let BuiltInTok(s) = text(fill: rgb("#003b4f"),raw(s))
#let CharTok(s) = text(fill: rgb("#20794d"),raw(s))
#let CommentTok(s) = text(fill: rgb("#5e5e5e"),raw(s))
#let CommentVarTok(s) = text(style: "italic",fill: rgb("#5e5e5e"),raw(s))
#let ConstantTok(s) = text(fill: rgb("#8f5902"),raw(s))
#let ControlFlowTok(s) = text(weight: "bold",fill: rgb("#003b4f"),raw(s))
#let DataTypeTok(s) = text(fill: rgb("#ad0000"),raw(s))
#let DecValTok(s) = text(fill: rgb("#ad0000"),raw(s))
#let DocumentationTok(s) = text(style: "italic",fill: rgb("#5e5e5e"),raw(s))
#let ErrorTok(s) = text(fill: rgb("#ad0000"),raw(s))
#let ExtensionTok(s) = text(fill: rgb("#003b4f"),raw(s))
#let FloatTok(s) = text(fill: rgb("#ad0000"),raw(s))
#let FunctionTok(s) = text(fill: rgb("#4758ab"),raw(s))
#let ImportTok(s) = text(fill: rgb("#00769e"),raw(s))
#let InformationTok(s) = text(fill: rgb("#5e5e5e"),raw(s))
#let KeywordTok(s) = text(weight: "bold",fill: rgb("#003b4f"),raw(s))
#let NormalTok(s) = text(fill: rgb("#003b4f"),raw(s))
#let OperatorTok(s) = text(fill: rgb("#5e5e5e"),raw(s))
#let OtherTok(s) = text(fill: rgb("#003b4f"),raw(s))
#let PreprocessorTok(s) = text(fill: rgb("#ad0000"),raw(s))
#let RegionMarkerTok(s) = text(fill: rgb("#003b4f"),raw(s))
#let SpecialCharTok(s) = text(fill: rgb("#5e5e5e"),raw(s))
#let SpecialStringTok(s) = text(fill: rgb("#20794d"),raw(s))
#let StringTok(s) = text(fill: rgb("#20794d"),raw(s))
#let VariableTok(s) = text(fill: rgb("#111111"),raw(s))
#let VerbatimStringTok(s) = text(fill: rgb("#20794d"),raw(s))
#let WarningTok(s) = text(style: "italic",fill: rgb("#5e5e5e"),raw(s))



#let article(
  title: none,
  subtitle: none,
  authors: none,
  keywords: (),
  date: none,
  abstract-title: none,
  abstract: none,
  thanks: none,
  cols: 1,
  lang: "en",
  region: "US",
  font: none,
  fontsize: 11pt,
  title-size: 1.5em,
  subtitle-size: 1.25em,
  heading-family: none,
  heading-weight: "bold",
  heading-style: "normal",
  heading-color: black,
  heading-line-height: 0.65em,
  mathfont: none,
  codefont: none,
  linestretch: 1,
  sectionnumbering: none,
  linkcolor: none,
  citecolor: none,
  filecolor: none,
  toc: false,
  toc_title: none,
  toc_depth: none,
  toc_indent: 1.5em,
  doc,
) = {
  // Set document metadata for PDF accessibility
  set document(title: title, keywords: keywords)
  set document(
    author: authors.map(author => content-to-string(author.name)).join(", ", last: " & "),
  ) if authors != none and authors != ()
  set par(
    justify: true,
    leading: linestretch * 0.65em
  )
  set text(lang: lang,
           region: region,
           size: fontsize)
  set text(font: font) if font != none
  show math.equation: set text(font: mathfont) if mathfont != none
  show raw: set text(font: codefont) if codefont != none

  set heading(numbering: sectionnumbering)

  show link: set text(fill: rgb(content-to-string(linkcolor))) if linkcolor != none
  show ref: set text(fill: rgb(content-to-string(citecolor))) if citecolor != none
  show link: this => {
    if filecolor != none and type(this.dest) == label {
      text(this, fill: rgb(content-to-string(filecolor)))
    } else {
      text(this)
    }
   }

  place(
    top,
    float: true,
    scope: "parent",
    clearance: 4mm,
    block(below: 1em, width: 100%)[

      #if title != none {
        align(center, block(inset: 2em)[
          #set par(leading: heading-line-height) if heading-line-height != none
          #set text(font: heading-family) if heading-family != none
          #set text(weight: heading-weight)
          #set text(style: heading-style) if heading-style != "normal"
          #set text(fill: heading-color) if heading-color != black

          #text(size: title-size)[#title #if thanks != none {
            footnote(thanks, numbering: "*")
            counter(footnote).update(n => n - 1)
          }]
          #(if subtitle != none {
            parbreak()
            text(size: subtitle-size)[#subtitle]
          })
        ])
      }

      #if authors != none and authors != () {
        let count = authors.len()
        let ncols = calc.min(count, 3)
        grid(
          columns: (1fr,) * ncols,
          row-gutter: 1.5em,
          ..authors.map(author =>
              align(center)[
                #author.name \
                #author.affiliation \
                #author.email
              ]
          )
        )
      }

      #if date != none {
        align(center)[#block(inset: 1em)[
          #date
        ]]
      }

      #if abstract != none {
        block(inset: 2em)[
        #text(weight: "semibold")[#abstract-title] #h(1em) #abstract
        ]
      }
    ]
  )

  if toc {
    let title = if toc_title == none {
      auto
    } else {
      toc_title
    }
    block(above: 0em, below: 2em)[
    #outline(
      title: toc_title,
      depth: toc_depth,
      indent: toc_indent
    );
    ]
  }

  doc
}

#set table(
  inset: 6pt,
  stroke: none
)
#import "@preview/fontawesome:0.5.0": *
#let brand-color = (:)
#let brand-color-background = (:)
#let brand-logo = (:)

#set page(
  paper: "a4",
  margin: (x: 2cm,),
  numbering: "1",
  columns: 1,
)

#show: doc => article(
  title: [Processing SEC submissions data],
  authors: (
    ( name: [Ian D. Gow],
      affiliation: [],
      email: [] ),
    ),
  date: [26 October 2026],
  font: ("Libertinus Serif",),
  fontsize: 10pt,
  heading-family: ("Libertinus Serif",),
  linkcolor: [\#0000FF],
  toc_title: [Table of contents],
  toc_depth: 3,
  doc,
)

#block[
This note describes how to use the #NormalTok("sec-submissions"); package to obtain and process the SEC's submissions data. The package converts the bulk JSON archive into Parquet, preserves the original timestamp text, and uses comparisons with earlier data and filing headers to produce time-zone-aware acceptance timestamps. I explain the evidence behind those corrections and report a sample-based assessment of the resulting data.

]
#block[
#callout(
body: 
[
This note describes the package workflow and reports the original September 30, 2026 audit alongside subsequent findings. New candidates treat live-file inference as provisional and can use filing-index references where SGML timestamps are absent. The #link("https://iangow.github.io/sec_submissions/timestamps/")[package methodology] and #link("https://iangow.github.io/sec_submissions/audit/")[audit documentation] give the maintained details. Each dated assessment concerns its own frozen candidate; it does not assess a later file.

]
, 
title: 
[
Methods and data versions
]
, 
background_color: 
rgb("#dae6fb")
, 
icon_color: 
rgb("#0758E5")
, 
icon: 
fa-info()
, 
body_background_color: 
white
)
]
In #link("https://iangow.github.io/notes/published/sec_submissions.html")[an earlier note], I described the structure of the SEC's submissions data and showed how to process those data using R. That note introduces JSON, list-columns, and the tools used to turn hierarchical data into tables. Here I focus on doing the work using my #link("https://github.com/iangow/sec_submissions")[#NormalTok("sec-submissions"); Python package], which brings together the extraction, timestamp-correction, and audit code used to prepare the data discussed below. I switched the bulk processing to Python for efficiency; the resulting Parquet files can still be analysed using R and DuckDB.

Since I wrote the earlier note, I have also found a problem with the acceptance timestamps supplied in newer submissions data. Some represent UTC and others New York local time, even when the text ends in #NormalTok("Z");. The package therefore produces two filings tables: #NormalTok("filings_raw.parquet");, with the original timestamp text, and #NormalTok("filings.parquet");, with time-zone-aware timestamps and information about how they were established. Keeping the two separate allows the interpretation to improve without losing the source data or extracting the JSON archive again. New candidates also retain the original text in #NormalTok("acceptanceDateTime_raw");, allowing later updates to compare source clocks even when an earlier interpretation was unresolved. #link("https://iangow.github.io/notes/published/datetimes.html")[My note on dates and times] discusses the additional issues that arise when analysing these timestamps.

The workflow has four stages: extract a dated snapshot, resolve timestamps using earlier evidence and new comparisons, collect filing headers for selected remaining cases, and audit a frozen candidate before release. Readers interested only in analysing the data can instead download the #link("https://github.com/iangow/sec_submissions_data/releases/latest/download/filings.parquet")[current corrected Parquet]. The examples below show how to prepare an update using the package; the reported results concern the #link("https://github.com/iangow/sec_submissions_data/releases/tag/2026-09-30")[30 September 2026 release]. Running the download examples later obtains a different SEC snapshot, which needs its own checks and audit.

= Getting started
<getting-started>
The package requires Python 3.12 or later. It is not yet on PyPI; install it from GitHub, including the optional dependencies used to calculate audit confidence bounds:

#Skylighting(([#ExtensionTok("python");#NormalTok(" ");#AttributeTok("-m");#NormalTok(" pip install ");#StringTok("'sec-submissions[audit] @ git+https://github.com/iangow/sec_submissions.git'");],));
The package uses #NormalTok("RAW_DATA_DIR"); for original ZIP snapshots and #NormalTok("DATA_DIR"); for Parquet files, supporting evidence, and audits. It reads these settings from a #NormalTok(".env"); file in the working directory, preserving values already set in the process environment. An optional configuration is:

#Skylighting(([#NormalTok("RAW_DATA_DIR=~/data/raw_data");],
[#NormalTok("DATA_DIR=~/data/pq_data");],
[#NormalTok("SEC_USER_AGENT=\"Your Name your.email@example.org\"");],));
Without these directory settings, the roots are #NormalTok("~/sec-submissions-data/raw_data"); and #NormalTok("~/sec-submissions-data/pq_data");. Each contains a #NormalTok("submissions/"); subdirectory, and explicit function arguments override the defaults. SEC requests require an identifying user agent; if one has not been configured, the first interactive request prompts for it and offers to save it. The package moderates concurrent requests in accordance with the SEC's #link("https://www.sec.gov/about/developer-resources")[developer guidance]. The #link("https://iangow.github.io/sec_submissions/data/")[data and directory guide] explains the layout, and the #link("https://iangow.github.io/sec_submissions/api/")[API reference] documents the functions used below.

For a first update, obtain a corrected reference and its supporting evidence:

#Skylighting(([#ImportTok("import");#NormalTok(" sec_submissions ");#ImportTok("as");#NormalTok(" sec");],
[],
[#NormalTok("reference ");#OperatorTok("=");#NormalTok(" sec.fetch_reference(version");#OperatorTok("=");#StringTok("\"2026-09-30\"");#NormalTok(")");],
[#NormalTok("reference.filings");],));
This downloads the dated corrected file, reusable JSON and SGML observations, source metadata, and audit artifacts. Every file is checked against its recorded size and SHA-256 checksum; interrupted downloads can resume, and verified local files are reused. Omit #NormalTok("version"); to obtain the current release, or add #NormalTok("companions=True"); for the other Parquet tables. These public GitHub downloads require neither a GitHub account nor an SEC user agent.

= From the bulk archive to Parquet
<from-the-bulk-archive-to-parquet>
The SEC provides #link("https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip")[a bulk submissions archive], which it #link("https://www.sec.gov/search-filings/edgar-application-programming-interfaces")[recompiles nightly]. Downloading that archive is more efficient than obtaining a separate JSON file for every CIK. Use the package to retain a dated snapshot and extract it:

#Skylighting(([#NormalTok("snapshot ");#OperatorTok("=");#NormalTok(" sec.download_submissions()");],
[#NormalTok("sec.extract_submissions(snapshot, max_seconds");#OperatorTok("=");#DecValTok("0");#NormalTok(")");],));
#NormalTok("download_submissions()"); saves the ZIP under the raw-data root and records its source URL, retrieval time, HTTP modification headers, size, and checksum in a small Parquet manifest. It does not overwrite an earlier snapshot. #NormalTok("extract_submissions()"); writes the following tables into a separate directory for that snapshot under the Parquet root.

#table(
  columns: (50%, 50%),
  align: (auto,auto,),
  table.header([File], [Contents],),
  table.hline(),
  [#NormalTok("filings_raw.parquet");], [Filing records, including the unaltered acceptance timestamp text],
  [#NormalTok("companies.parquet");], [Company metadata from each primary CIK file],
  [#NormalTok("addresses.parquet");], [Business and mailing addresses],
  [#NormalTok("tickers.parquet");], [Tickers and exchanges],
  [#NormalTok("former_names.parquet");], [Former names and their date ranges],
  [#NormalTok("files.parquet");], [References to historical filing files, including whether they are present in the archive],
)
The extractor reads every primary CIK file and the historical files that it references, retaining #NormalTok("cik"); and #NormalTok("source_file"); so that each filing row can be traced to its source. It does not start from a selected list of companies. Historical files referenced more than once by a company are read only once for that company; absent files are recorded in #NormalTok("files.parquet"); but their filing rows cannot be recovered from the ZIP. Company metadata describes the downloaded snapshot, not necessarily the company as it existed on each filing date.

Dates such as #NormalTok("filingDate"); and #NormalTok("reportDate"); are written as dates, while identifiers that may contain leading zeros remain text. #NormalTok("acceptanceDateTime"); remains text, including any suffix and fractional seconds: extraction makes no decision about the time zone represented by that text. The other tables do not need separate raw versions because they do not contain acceptance timestamps.

The extractor saves checkpoints. By default it returns after about 150 seconds; repeating the call resumes the same extraction. The example uses #NormalTok("max_seconds=0"); to continue until completion. Do not replace the source ZIP while resuming an associated checkpoint. Using a separate directory for each snapshot also prevents its companion tables from replacing those of another snapshot.

= Establishing the timestamps
<establishing-the-timestamps>
The unit to which the package attaches a corrected timestamp is the #strong[accession number]. A filing may appear under more than one CIK, but those appearances should refer to the same acceptance instant. An accepted correction is therefore joined to every occurrence of that accession when producing the candidate file. A rule for an entire archived CIK file is not sufficient: its timestamps can have mixed interpretations.

== The first update and later updates
<the-first-update-and-later-updates>
Our original analysis had a useful starting point: the May 2024 archive used a consistent New York local-clock convention. The first update compared a Parquet reference derived from that archive with the ZIP downloaded on 5 September 2026, then used duplicate-accession comparisons, live JSON, and selected SGML headers to address the remaining cases. The package's #NormalTok("make_previous()"); function supports that historical bootstrap, but the 2024 convention is not a rule for newer snapshots.

The second update started from the corrected September 5 Parquet and processed the September 30 ZIP. Readers need not repeat either historical preparation: the downloadable September 30 reference incorporates that work and can serve as the starting point for their next update. Thereafter, their own preceding corrected Parquet can provide the reference.

Create an initial candidate using the newly extracted data and available evidence:

#Skylighting(([#NormalTok("sec.process()");],));
With the default layout, #NormalTok("process()"); uses the latest extracted #NormalTok("filings_raw.parquet"); and the local #NormalTok("DATA_DIR/submissions/filings.parquet"); as its predecessor when that file exists. Otherwise it uses the downloaded reference. It reuses the reference's observations and locally collected JSON/SGML evidence, writes a fresh numbered candidate such as #NormalTok("filings_candidate_0001.parquet");, and saves diagnostics beside it. It does not download new SEC evidence or replace the current release. Explicit inputs are available for controlled comparisons, as described in the #link("https://iangow.github.io/sec_submissions/workflow/")[workflow guide].

Only supported prior instants can act as anchors. For each accession, the usable prior rows must agree on one instant, and interpreting a new raw clock as either UTC or #NormalTok("America/New_York"); must reproduce that instant. A previously unresolved Eastern fallback or provisional live-file inference is not an anchor. Its observed source clock may nevertheless supply one member of a new exact clock pair. The processor can use the preserved #NormalTok("acceptanceDateTime_raw"); column or explicitly supplied historical raw files, rather than treating a converted provisional guess as another observation. Changes in non-timestamp fields come from the newly extracted archive.

== Resolve differing clocks first
<resolve-differing-clocks-first>
An accession appearing under several CIKs may have different raw clocks. Comparisons with the previous snapshot or live submissions JSON may also reveal a second clock for the same accession. The useful case has exactly two distinct valid clocks that resolve to one instant when the earlier clock is interpreted as #NormalTok("America/New_York"); and the later as UTC. For example, 08:01:07 in New York on a December date and 13:01:07 UTC on that date describe the same instant.

The package tests that equality using the named time zones, accounting for daylight saving and changes of date. A difference of four or five hours alone is insufficient. Neither the newer snapshot nor the live JSON is assumed to supply the UTC member: either source may provide the later clock reading. Equal clocks provide no new timezone evidence, and unexplained differences remain available for investigation. This comparison does not require a filing to be outside ordinary EDGAR hours.

== Use live-file evidence carefully
<use-live-file-evidence-carefully>
One live JSON response can provide observations for many accessions. Where a direct pair cannot resolve an accession, supported prior instants, resolved clock pairs, and SGML observations can anchor the interpretation of that response. If all available anchors agree, the package can apply the inferred convention to its other observed clocks.

A live response can contain both UTC and Eastern clocks, even when the available anchors suggest a common convention. The resulting proposals are therefore #strong[provisional], not confirmations. The package records the anchors, rejects contradictory file evidence, and never promotes a provisional proposal to confirming evidence in a subsequent update. It identifies a response version by its source URL and retrieval time: a later response from the same URL need not use the same convention. It does not apply a live-file convention indiscriminately to all rows in the ZIP or to future accessions not observed in that response.

An already established accession instant can usually be reused without fetching its JSON or SGML again, provided the new raw clock reproduces it. That is the principal saving in a subsequent update. It is different from assuming that all new filings for an earlier CIK must use the same time zone.

= Collecting additional evidence
<collecting-additional-evidence>
The initial candidate identifies what the existing observations cannot resolve. It is useful to screen unresolved and provisional recent filings, not only those outside ordinary EDGAR hours: a UTC clock can fall within that window and still be misinterpreted as Eastern. For example, collect live JSON for files containing unresolved records from 2024 onward, then process the data again:

#Skylighting(([#ImportTok("from");#NormalTok(" datetime ");#ImportTok("import");#NormalTok(" date");],
[],
[#NormalTok("sec.collect_live_json(since_date");#OperatorTok("=");#NormalTok("date(");#DecValTok("2024");#NormalTok(", ");#DecValTok("1");#NormalTok(", ");#DecValTok("1");#NormalTok("), workers");#OperatorTok("=");#DecValTok("8");#NormalTok(", rate");#OperatorTok("=");#DecValTok("5");#NormalTok(")");],
[#NormalTok("sec.process()");],));
The collector freezes the selected set of source files, fetches matching raw accessions, and follows linked historical JSON when necessary. It includes already supported accessions in those files so that they can serve as anchors. Its Parquet observations preserve source URLs and retrieval times; a completed request queue does not imply that every accession was found or every timestamp resolved. The recent cutoff defines the collection scope, not a claim that older unsupported timestamps are correct. Workers overlap network waits, while #NormalTok("rate"); limits total requests per second across those workers.

JSON comparisons should precede a large SGML queue because one response can resolve many timestamps. For remaining questions, the archived filing header's #NormalTok("<ACCEPTANCE-DATETIME>"); field provides an accession-level reference, interpreted here as a New York local clock and converted using #NormalTok("America/New_York");. An exact SGML observation has priority over weaker file-level inference, while disagreements remain in the diagnostics.

#NormalTok("collect_sgml()"); expects an explicit queue with #NormalTok("cik"); and #NormalTok("accession_number"); columns; it does not automatically select an anchor for every unresolved file. After preparing such a queue from the candidate and its coverage diagnostics, collect it and create another candidate:

#Skylighting(([#NormalTok("sec.collect_sgml(");#StringTok("\"sgml_queue.parquet\"");#NormalTok(", workers");#OperatorTok("=");#DecValTok("8");#NormalTok(", rate");#OperatorTok("=");#DecValTok("5");#NormalTok(",");],
[#NormalTok("                 index_fallback");#OperatorTok("=");#VariableTok("True");#NormalTok(")");],
[#NormalTok("sec.process()");],));
Possible selections include missing live matches, contradictory evidence, and live response versions without anchors. For the September 30 update, the follow-up used one accession for single-accession response versions and the first and last accessions for multi-accession versions. The queue contained 23,906 accessions; 23,905 supplied a timestamp tag and one returned 404. That historical anchoring design relied on a common-convention assumption. The current package retains such inferences as provisional; an independent audit addresses a different question.

An outside-hours screen remains useful for diagnosis, but an outside-hours time is not automatically an error. #NormalTok("EFFECT"); is excluded from that screen, and the targeted anchor collection also excluded #NormalTok("CORRESP");, #NormalTok("UPLOAD");, and #NormalTok("DRSLTR");. Those forms can still participate in exact clock-pair comparisons and the random audit. Their form names or a global date cutoff should not determine their time zone.

Successful SGML observations, missing timestamp tags, and request errors are retained separately. Transient request failures can be retried. Where an SGML tag is absent, filing-index fallback reads the labelled #NormalTok("Accepted"); value and retains its source separately; an unsuccessful lookup remains unavailable evidence. Likewise, literal midnight is a useful diagnostic, not a sufficient rule for declaring a timestamp missing. Historical date-only values must remain distinguishable from observed acceptance times: midnight Eastern is a storage convention for those dates, not evidence of an intraday acceptance time. The collection functions support resumption with the same inputs and settings; see the workflow guide for those options.

= The candidate and its provenance
<the-candidate-and-its-provenance>
Every processing run combines the evidence into one accession-level interpretation and writes a separate candidate with time-zone-aware #NormalTok("acceptanceDateTime"); values. The package uses a temporary DuckDB database for this computation, exports the candidate and Parquet diagnostics, and removes the working database. Readers do not need to create or maintain a permanent database.

Rows without an accepted instant retain an Eastern-time interpretation labelled #NormalTok("unresolved_raw_as_eastern");. That is a compatibility fallback, not a verified timestamp. The output's #NormalTok("timestamp_provenance");, #NormalTok("timestamp_reference_id");, and #NormalTok("timestamp_interpretation"); preserve the distinction between established instants, inferred conventions, and unresolved cases. For example, #NormalTok("sgml"); denotes direct header evidence and #NormalTok("provisional_live_file_inferred"); denotes a proposed live-file convention. The older #NormalTok("live_file_inferred"); label must likewise be treated as provisional when reading the frozen September 30 release. Current diagnostics count supported, provisional, and unresolved rows separately.

The main Parquet therefore carries the accepted instants and their status forward. The separate observation files retain source clocks, failed attempts, retrieval versions, and evidence for accessions that may be absent from a later snapshot. Diagnostics record the inputs, support counts, rejected evidence, and disagreements. Check these alongside row counts and non-timestamp fields before releasing the candidate. Request completion, evidence-supported coverage, and an accuracy estimate are different things.

= Checking quality with a sample
<checking-quality-with-a-sample>
The checks used to find and correct problems do not estimate the frequency of errors in the released data. A collection concentrated on recent or outside-hours filings is not representative of all filing rows. For that purpose, draw a probability sample from a frozen candidate. Readers using the published data can inspect the results and downloadable audit artifacts without repeating this collection themselves.

== Freeze predictions before fetching headers
<freeze-predictions-before-fetching-headers>
The population assessed here is the rows of #NormalTok("filings.parquet");, including repeated appearances of an accession under different CIKs. An accession-level accuracy estimate answers a different question. All form types belong in this audit; a sample limited to unresolved cases cannot establish the accuracy of the whole file.

The current audit uses SGML first and the filing index's labelled #NormalTok("Accepted"); value when the SGML tag is absent. Use the package to draw and audit a reproducible simple random sample:

#Skylighting(([#NormalTok("sec.audit(sample_size");#OperatorTok("=");#DecValTok("10_000");#NormalTok(", seed");#OperatorTok("=");#DecValTok("202609304");#NormalTok(", workers");#OperatorTok("=");#DecValTok("8");#NormalTok(", rate");#OperatorTok("=");#DecValTok("5");#NormalTok(")");],));
By default this selects the latest candidate, saves the sampled row keys and predicted instants before fetching SGML, and does not reuse an observation cache. It uses seeded reservoir sampling, retains repeated appearances of an accession in the sample, and deduplicates only the fetch queue. It never changes the candidate or its frozen predictions. The seed alone does not reproduce the published sample for another file; the candidate's identity and the saved identifiers matter too.

The output includes sample identifiers, frozen predictions, observation batches, row-level outcomes, and a summary. Record agreement, disagreement, missing timestamp tags, and request failures separately, retrying transient failures without changing sample membership. Do not replace sampled rows because their headers are unavailable. An audit used to repair a candidate must be followed by a new independent assessment of the revised candidate. The processor does not automatically use a candidate's own audit observations as repair evidence; those observations can be retained for a subsequent update.

A fresh header lookup does not make every comparison independent of the original evidence. Where an SGML timestamp already supported the prediction, agreement checks application of that evidence rather than independently establishing the header's timezone semantics. Report outcomes by evidence group where sample sizes permit, as below.

== What the sample can establish
<what-the-sample-can-establish>
If there are zero disagreements in $n$ verifiable observations, the one-sided 95% binomial upper bound on the error rate is

$ p_U = 1 - 0.05^(1 \/ n) . $

For a small sampling fraction, this is a conservative approximation for sampling rows without replacement. It is close to $3 \/ n$: zero errors in 600 verifiable observations gives a bound of about 0.5%, and zero in 3,000 gives about 0.1%. With observed errors, use an appropriate binomial interval rather than only the sample error percentage; #link("https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm")[NIST describes exact binomial confidence limits]. The package calculates a one-sided exact bound using the optional audit dependencies installed above.

Unavailable timestamps limit the conclusion. A bound among verifiable rows does not establish whether rows without reference timestamps are correct, so it is not valid to call the entire file 99.9% accurate merely because 3,000 obtainable headers agree. Diagnostic samples of recent filings, correspondence forms, or suspicious clocks can be useful additions, but must remain separate from the overall estimate unless they form part of a probability design with appropriate weights.

== Results for the September 30 update
<results-for-the-september-30-update>
The worked example's first ZIP, downloaded on 5 September 2026, contained 27,209,834 filing rows, with filings dated through 4 September. The September 30 ZIP was retrieved at 13:39 UTC, had an HTTP modification time of 12:34:49 UTC that day, and supplied 27,272,863 filing rows. The #link("https://github.com/iangow/sec_submissions_data/releases/download/2026-09-30/manifest.json")[release manifest] records its checksum, the released candidate's checksum, and the audit metadata.

The frozen September 30 file labels 25,584,390 timestamps as supported under the policy used for that release, alongside 1,688,473 explicitly unresolved Eastern fallbacks. That historical supported count includes live-file inference, which the current package treats as provisional. The following results describe the original SGML-only audit of that file. A fresh 10,000-row sample was frozen before new SGML lookup, using seed #NormalTok("202609304");. The audit found no disagreements among the 9,230 rows with verifiable headers. The exact one-sided 95% upper bound on the error rate among those verifiable rows is #strong[0.0325%].

#table(
  columns: 4,
  align: (auto,right,right,right,),
  table.header([Candidate evidence group], [Sample rows], [Verifiable], [Disagreements],),
  table.hline(),
  [Trusted 2024 snapshot], [6,702], [6,695], [0],
  [ZIP/live-JSON clock pairs], [1,446], [1,445], [0],
  [Live-file inference], [953], [862], [0],
  [Cross-CIK accession pairs], [173], [99], [0],
  [Direct SGML evidence], [129], [129], [0],
  [Snapshot-pair inference], [1], [0], [n/a],
  [Unresolved Eastern fallback], [596], [0], [n/a],
  [#strong[Total]], [#strong[10,000]], [#strong[9,230]], [#strong[0]],
)
All 770 unavailable references lacked the SGML timestamp tag; none remained unavailable because of a failed request. They were filings dated 1994 through 2002, with no missing tags observed for 2003 onward in this sample. In particular, none of the sampled unresolved fallbacks was verifiable: the result does not validate those rows. The #link("https://github.com/iangow/sec_submissions_data/releases/download/2026-09-30/audit_sample.csv")[sample identifiers and frozen predictions] and #link("https://github.com/iangow/sec_submissions_data/releases/download/2026-09-30/audit_outcomes.parquet")[row-level outcomes] make the assessment transparent without listing 10,000 records in the note. These results remain a dated record of that original assessment.

== Subsequent findings
<subsequent-findings>
A follow-up obtained a filing-index reference for each of the 770 missing-tag rows while retaining the original sample and predictions. Seven supplied acceptance times that agreed exactly; the other 763 were historical date-only values whose dates agreed with the source. Of those date-only values, 52 had an incorrect midnight representation in the frozen file. This distinction matters: agreement on the date is not agreement on an observed acceptance instant.

An independent October 2 audit of a later pair-corrected candidate found two disagreements in 10,000 rows, with all rows verifiable using 9,234 SGML and 766 filing-index references. Both disagreements arose from a live-response-wide timezone convention, which led to the package's provisional treatment of such inferences. The observed disagreement rate for that candidate was 0.020%, with a one-sided 95% upper bound of 0.06294%.

Later targeted collection and checks against saved samples verified repairs, but those are regression checks rather than a new independent estimate for the repaired file. A newly frozen random audit remains the release gate for that candidate. The #link("https://iangow.github.io/sec_submissions/audit/")[maintained audit report] identifies each candidate, the original observations, the supplemental references, and the limits of the comparisons.

= Releasing an update
<releasing-an-update>
After reviewing the candidate, diagnostics, and audit, install the candidate as the local current file:

#Skylighting(([#NormalTok("sec.publish()");],));
This writes #NormalTok("DATA_DIR/submissions/filings.parquet");. If a release already exists, the publisher first saves it as #NormalTok("filings_previous.parquet"); and moves an older previous version into a dated #NormalTok("archive/"); entry. It validates the copied bytes and preserves the existing current file's local identity. The in-place update is not atomic for other readers, so they should wait until it finishes. The package does not upload the data or perform storage-service-specific link checks.

For the public reference, I attach the validated files and a checksum manifest to a dated release in a separate #link("https://github.com/iangow/sec_submissions_data")[data repository]. All files are uploaded to a draft release and checked before it becomes public. The #link("https://github.com/iangow/sec_submissions_data/releases/latest/download/filings.parquet")[current-file link] follows the latest release; a #link("https://github.com/iangow/sec_submissions_data/releases/download/2026-09-30/filings.parquet")[dated link] identifies a fixed snapshot. The package's #NormalTok("fetch_reference()"); resolves the current release once and downloads its files from that dated version, avoiding a mixture of releases.

For the next update, retain the preceding corrected Parquet and its supporting observations, then repeat extraction, comparison, bounded evidence collection, and an independent audit. The earlier ZIP is useful for reproducibility but need not be reprocessed to carry its established accession instants forward. The command-line equivalents of the functions shown here are documented in the #link("https://iangow.github.io/sec_submissions/workflow/")[package workflow guide].
