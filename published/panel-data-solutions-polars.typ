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
#show raw.where(block: true): set text(size: 8pt)
#set par(justify: false)
#set bibliography(title: none)
#let brand-color = (:)
#let brand-color-background = (:)
#let brand-logo = (:)

#set page(
  paper: "a4",
  margin: (x: 2cm,y: 2cm,),
  numbering: "1",
  columns: 1,
)

#show: doc => article(
  title: [Solutions for Panel data],
  subtitle: [Updated Python Polars solutions],
  authors: (
    ( name: [Ian D. Gow],
      affiliation: [],
      email: [] ),
    ),
  date: [26 October 2026],
  font: ("Libertinus Serif",),
  fontsize: 10pt,
  heading-family: ("Libertinus Serif",),
  sectionnumbering: "1.1.a",
  toc_title: [Table of contents],
  toc_depth: 3,
  doc,
)

These solutions accompany the #link("https://iangow.github.io/era_pl_book/panel-data.html")[Panel data chapter] of #emph[Empirical Research in Accounting: Tools and Methods]. This notes edition updates the solutions discussed in the original 2026-05-20 post with subsequent corrections and clarifications; it is not a facsimile of the original LinkedIn attachment. The calculations were freshly executed on 26 October 2026.

The calculations use a local Parquet repository, with #NormalTok("DATA_DIR"); pointing to that repository. See the book's #link("https://iangow.github.io/era_pl_book/intro.html")[data setup instructions] and the accompanying #link("https://iangow.github.io/notes/published/linkedin-solutions-requirements.txt")[Python requirements]. The QMD uses the existing #NormalTok("era_pl_sols"); Jupyter kernel, whose environment supplies those packages; its code does not import either solutions repository. Changes in the input data or software can change estimates and timings.

= Exercises
<exercises>
+ Generate a random sample of test scores using #NormalTok("get_test_scores()"); with some value of #NormalTok("effect_size"); and some value of #NormalTok("seed");. Assign this to the variable #NormalTok("df_1");. Estimate the model #NormalTok("\"score ~ I(treat * post) | grade + id\""); using #NormalTok("pf.feols()"); with #NormalTok("data=df_1"); and #NormalTok("vcov=\"iid\""); and store the result in #NormalTok("fm");. Compare the output of #NormalTok("fm.tidy()"); with that from #NormalTok("fit_test_score_panel(df_1, vcov=\"iid\")");. What do you observe?

  Estimate the model #NormalTok("\"score ~ I(treat * post) | grade + id\""); using #NormalTok("pf.feols()"); with #NormalTok("data=df_1"); and #NormalTok("vcov={\"CRV1\": \"grade + id\"}"); and store the result in #NormalTok("fm2");. Compare the output of #NormalTok("fm2.tidy()"); with that from #NormalTok("fit_test_score_panel(df_1, vcov={\"CRV1\": \"grade + id\"})");. What do you observe?

#Skylighting(([#NormalTok("df_1 ");#OperatorTok("=");#NormalTok(" get_test_scores(effect_size");#OperatorTok("=");#FloatTok("0.1");#NormalTok(", seed");#OperatorTok("=");#DecValTok("100");#NormalTok(")");],
[],
[#NormalTok("fm ");#OperatorTok("=");#NormalTok(" pf.feols(");],
[#NormalTok("    ");#StringTok("\"score ~ I(treat * post) | grade + id\"");#NormalTok(",");],
[#NormalTok("    data");#OperatorTok("=");#NormalTok("df_1,");],
[#NormalTok("    vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok(",");],
[#NormalTok(")");],
[],
[#NormalTok("fm2 ");#OperatorTok("=");#NormalTok(" pf.feols(");],
[#NormalTok("    ");#StringTok("\"score ~ I(treat * post) | grade + id\"");#NormalTok(",");],
[#NormalTok("    data");#OperatorTok("=");#NormalTok("df_1,");],
[#NormalTok("    vcov");#OperatorTok("=");#NormalTok("{");#StringTok("\"CRV1\"");#NormalTok(": ");#StringTok("\"grade + id\"");#NormalTok("},");],
[#NormalTok(")");],
[],
[#NormalTok("fit_test_score_panel(df_1, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok(")");],));
#table(
  columns: 4,
  align: (auto,auto,auto,auto,),
  table.header([estimate], [se], [t], [p\_value],
    [f64], [f64], [f64], [f64],),
  table.hline(),
  [1.000819], [0.31368], [3.190576], [0.001435],
)
#Skylighting(([#NormalTok("fit_test_score_panel(df_1, vcov");#OperatorTok("=");#NormalTok("{");#StringTok("\"CRV1\"");#NormalTok(": ");#StringTok("\"grade + id\"");#NormalTok("})");],));
#table(
  columns: 4,
  align: (auto,auto,auto,auto,),
  table.header([estimate], [se], [t], [p\_value],
    [f64], [f64], [f64], [f64],),
  table.hline(),
  [1.000819], [0.930173], [1.075949], [0.360774],
)
The outputs match the corresponding rows from #NormalTok("fm.tidy()"); and #NormalTok("fm2.tidy()"); for the treatment-effect coefficient. The helper returns just the quantities needed for the simulation analysis: the estimate, standard error, $t$-statistic, and $p$-value.

#block[
#set enum(numbering: "1.", start: 2)
+ Given the above, why do you think we included #NormalTok("fit_test_score_panel()"); rather than using #NormalTok("pf.feols()");? Develop and run a test of your hypothesis for why we did so.
]

The likely reason is speed. The chapter runs the same two-way fixed-effects regression many times in simulation, and #NormalTok("fit_test_score_panel()"); is specialized to this exact setting. The following code compares the two approaches over a modest number of replications.

#Skylighting(([#ImportTok("import");#NormalTok(" time");],
[],
[#NormalTok("num_runs ");#OperatorTok("=");#NormalTok(" ");#DecValTok("50");],
[#NormalTok("sim_dfs ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    get_test_scores(effect_size");#OperatorTok("=");#DecValTok("0");#NormalTok(", seed");#OperatorTok("=");#NormalTok("i)");],
[#NormalTok("    ");#ControlFlowTok("for");#NormalTok(" i ");#KeywordTok("in");#NormalTok(" ");#BuiltInTok("range");#NormalTok("(num_runs)");],
[#NormalTok("]");],
[],
[#NormalTok("start ");#OperatorTok("=");#NormalTok(" time.perf_counter()");],
[#NormalTok("_ ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    pf.feols(");],
[#NormalTok("        ");#StringTok("\"score ~ I(treat * post) | grade + id\"");#NormalTok(",");],
[#NormalTok("        data");#OperatorTok("=");#NormalTok("df,");],
[#NormalTok("        vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok(",");],
[#NormalTok("    ).coef()[");#StringTok("\"I(treat * post)\"");#NormalTok("]");],
[#NormalTok("    ");#ControlFlowTok("for");#NormalTok(" df ");#KeywordTok("in");#NormalTok(" sim_dfs");],
[#NormalTok("]");],
[#NormalTok("pyfixest_time ");#OperatorTok("=");#NormalTok(" time.perf_counter() ");#OperatorTok("-");#NormalTok(" start");],
[],
[#NormalTok("start ");#OperatorTok("=");#NormalTok(" time.perf_counter()");],
[#NormalTok("_ ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    fit_test_score_panel(df, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok(").item(");#DecValTok("0");#NormalTok(", ");#StringTok("\"estimate\"");#NormalTok(")");],
[#NormalTok("    ");#ControlFlowTok("for");#NormalTok(" df ");#KeywordTok("in");#NormalTok(" sim_dfs");],
[#NormalTok("]");],
[#NormalTok("helper_time ");#OperatorTok("=");#NormalTok(" time.perf_counter() ");#OperatorTok("-");#NormalTok(" start");],
[],
[#NormalTok("pl.DataFrame({");],
[#NormalTok("    ");#StringTok("\"method\"");#NormalTok(": [");#StringTok("\"pyfixest\"");#NormalTok(", ");#StringTok("\"fit_test_score_panel\"");#NormalTok("],");],
[#NormalTok("    ");#StringTok("\"seconds\"");#NormalTok(": [pyfixest_time, helper_time],");],
[#NormalTok("    ");#StringTok("\"runs\"");#NormalTok(": [num_runs, num_runs],");],
[#NormalTok("}).with_columns(");],
[#NormalTok("    seconds_per_run");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"seconds\"");#NormalTok(") ");#OperatorTok("/");#NormalTok(" pl.col(");#StringTok("\"runs\"");#NormalTok(")");],
[#NormalTok(").with_columns(");],
[#NormalTok("    pl.col(");#StringTok("\"seconds\"");#NormalTok(", ");#StringTok("\"seconds_per_run\"");#NormalTok(").");#BuiltInTok("round");#NormalTok("(");#DecValTok("4");#NormalTok(")");],
[#NormalTok(").style");],));
#figure([
#{set text(font: ("Libertinus Serif",) , size: 10pt); table(
  columns: 4,
  align: (left,right,right,right,),
  table.header(table.cell(align: bottom + left, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); method], table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); seconds], table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); runs], table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); seconds\_per\_run],),
  table.hline(),
  table.cell(align: horizon + left)[pyfixest], table.cell(align: horizon + right)[0.2754], table.cell(align: horizon + right)[50], table.cell(align: horizon + right)[0.0055],
  table.cell(align: horizon + left)[fit\_test\_score\_panel], table.cell(align: horizon + right)[0.0087], table.cell(align: horizon + right)[50], table.cell(align: horizon + right)[0.0002],
)}
], caption: figure.caption(
position: top, 
[
Timing comparison for simulated panel regressions
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-panel-speed>


The timing table measures the relative speed of the helper and the general estimator in this run. The exact times depend on the computer, software versions and workload. That speed matters because the chapter uses 1,000 replications in several settings.

= Discussion questions
<discussion-questions>
+ The proprietary cost hypothesis tested by #cite(<Li:2018tj>, form: "prose") posits that increased cost of disclosure will lead to reduced supply of disclosure. What rival theories exist that would make alternative predictions? Are there other elements of disclosure theory that might be tested? Why do you think #cite(<Li:2018tj>, form: "prose") focused on this specific element of the proprietary cost hypothesis?

There are no clear rival theories other than "no effect". Of course, "no effect" is unlikely to be found in a published paper for reasons discussed in #link("https://iangow.github.io/era_pl_book/natural-revisited.html")[Chapter 19]. There are other elements of the theory that might be examined, such as the firms with good news (observed in later realizations) being the ones who disclose and the market reacting favourably to disclosure. At times it seems the least interesting aspect of "proprietary cost hypothesis" gets studied again and again in "increasingly clever" ways.

#block[
#set enum(numbering: "1.", start: 2)
+ In the analysis above, we do not include the control variables considered by #cite(<Li:2018tj>, form: "prose"). For example, #cite(<Li:2018tj>, form: "prose") "include R&D expenditures to sales, advertisement \[sic\] expenditure to sales, and intangible assets scaled by total assets to control for a firm's proprietary costs of disclosure." Using the approach outlined in #link("https://iangow.github.io/era_pl_book/causal-inf.html")[Chapter 4], in what circumstances would it be necessary to control for "a firm's proprietary costs of disclosure" in this way? Do these circumstances seem applicable in this setting, where the treatment is a (presumably exogenous) shock to disclosure costs and the outcome is disclosure choices?
]

The first question is whether a proposed control is a pre-treatment common cause, a precision variable, or a variable affected by IDD. Controlling for proprietary costs changed by IDD could block the proposed mechanism. A better interpretation is simply that the wording used by #cite(<Li:2018tj>, form: "prose") is poor. Instead, #cite(<Li:2018tj>, form: "prose") are in effect using IDD adoption as an exogenous shock to the treatment. This is like using IDD adoption as an instrument, but focused on #emph[intent-to-treat] analyses.#footnote[Recall from Table 1 of #cite(<Hoekstra:2009wp>, form: "prose") that an intent-to-treat analysis regresses the outcome directly on the instrument.]

Intent-to-treat analyses are common when researchers have an instrument, but do not observe the treatment of interest directly.#footnote[#cite(<Bloomfield:2021va>, form: "prose") focuses on intent-to-treat analyses, even though the treatment is observed.] In this setting, the treatment of interest is "proprietary costs of disclosure" and a maintained assumption is that IDD adoption is random, has a direct causal effect on proprietary costs of disclosure, and does not affect the outcome (in this setting, voluntary disclosure of customer identities) except through its effect on the treatment. This can be represented on a causal diagram as in #ref(<fig-iv-llz>, supplement: [Figure]).

In conventional IV analyses, it is considered a standard step to evaluate the relationship between the instrument ($Z$) and the treatment ($X$) statistically.#footnote[As always, remember that the critical assumption is #emph[causal] not #emph[statistical], but statistical analysis is necessary to check for problems in the finite-sample behaviour of IV analyses.] But this is not possible when the treatment is not observed. As such, in addition to assumptions about the causal relationship between $Z$ and $X$, the magnitude of the proprietary-cost change is unobserved. A reduced-form effect of IDD exposure does not require dividing by a measured first stage, but it does not identify the effect per unit of proprietary costs. So we need to assume that IDD adoption has a causal effect on proprietary costs of disclosure and the empirical tests are joint tests of that assumption and the hypothesis that increased costs of disclosure lead to reduced supply of disclosure.#footnote[My own view is that it is quite obvious that increased costs of disclosure lead to reduced supply of disclosure and that the paper is really a test of the effect of IDD adoption on proprietary costs of disclosure. For reasons that will become evident by the end of this document, I think the evidence from the setting in #cite(<Li:2018tj>, form: "prose") is very far from persuasive.]

#figure([
#box(image("panel-data-solutions-polars_files/figure-typst/fig-iv-llz-output-1.svg"))
], caption: figure.caption(
position: bottom, 
[
Causal diagram for #cite(<Li:2018tj>, form: "prose")
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-iv-llz>


The variables that need to be controlled for are any determinants of "a firm's proprietary costs of disclosure" that also affect the instrument. If IDD exposure were randomly assigned, baseline controls could improve precision. If it is only as-if random conditional on measured factors, those factors matter for identification; time-varying confounders and conditional parallel trends remain relevant. Post-treatment measures of proprietary costs should not be added mechanically. But #cite(<Li:2018tj>, form: "prose") no doubt understood that in accounting research it's important to "control for stuff".

#block[
#set enum(numbering: "1.", start: 3)
+ What differs between the regressions reported in columns (1) and (3), and (2) and (4) of #ref(<tbl-table-2>, supplement: [Table]), respectively? Does this tell you anything about what drives the regression results in this setting? What happens if you omit the year fixed effects from both sets of regressions? What does this tell you about the role of the "non-switchers" (i.e., firms not in the #NormalTok("switchers"); data frame) in the regression?
]

In the regression output below, warnings from #NormalTok("pyfixest"); about singleton fixed effects and collinear event-time indicators are suppressed. These warnings reflect observations or indicators that the fixed-effects estimator drops automatically; they do not affect the interpretation of the reported coefficients.

#figure([
#table(
  columns: (auto, 1fr, 1fr, 1fr, 1fr), align: (left, center, center, center, center),
  column-gutter: (0em, 0.5em, 0.5em, 0.5em),
  stroke: none, row-gutter: 0.2em,
  table.hline(stroke: 0.08em),
  [], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]],
  table.hline(stroke: 0.03em, start: 1, end: 2),
  table.hline(stroke: 0.03em, start: 2, end: 3),
  table.hline(stroke: 0.03em, start: 3, end: 4),
  table.hline(stroke: 0.03em, start: 4, end: 5),
  [], [(1)], [(2)], [(3)], [(4)],
  table.hline(stroke: 0.05em),
  table.hline(stroke: 0.03em),
  [post], [0.016\*\* \ (0.008)], [0.024\*\*\* \ (0.008)], [0.014 \ (0.009)], [0.019\*\* \ (0.01)],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [gvkey], [x], [x], [x], [x],
  [year], [x], [x], [x], [x],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [Sample], [All], [All], [Switchers], [Switchers],
  [Observations], [28,230], [23,923], [3,611], [3,154],
  [$R^2$], [0.665], [0.703], [0.623], [0.66],
  table.hline(stroke: 0.08em),
  [#table.cell(colspan: 5)[#text(size: 10pt)[Significance levels: \* p \< 0.1, \*\* p \< 0.05, \*\*\* p \< 0.01. Format of coefficient cell: Coefficient   (Std. Error)]]],
)
], caption: figure.caption(
position: top, 
[
Effect of IDD adoption
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-table-2>


#emph[What differs between the regressions reported in columns (1) and (3), and (2) and (4) of #ref(<tbl-table-2>, supplement: [Table]), respectively?]

The samples are different. Columns (1) and (2) include all firms, while columns (3) and (4) only include the "switchers" (defined above as firms whose treatment status changed during the sample period).

#emph[What happens if you omit the year fixed effects from both sets of regressions?]

It is easy to tweak the code to omit #NormalTok("year"); fixed effects:

#block[
#Skylighting(([#NormalTok("fms_no_year ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ post | gvkey\"");#NormalTok(", data");#OperatorTok("=");#NormalTok("reg_data, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ post | gvkey\"");#NormalTok(", data");#OperatorTok("=");#NormalTok("reg_data, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ post | gvkey\"");#NormalTok(", data");#OperatorTok("=");#NormalTok("reg_data_switchers, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ post | gvkey\"");#NormalTok(", data");#OperatorTok("=");#NormalTok("reg_data_switchers, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("]");],));
]
Results are reported in #ref(<tbl-no-year-fe>, supplement: [Table]). Without year fixed effects, the treatment coefficients agree between the full and switcher samples. The observation counts and standard errors can differ, so the complete regression results are not identical.

#figure([
#table(
  columns: (auto, 1fr, 1fr, 1fr, 1fr), align: (left, center, center, center, center),
  column-gutter: (0em, 0.5em, 0.5em, 0.5em),
  stroke: none, row-gutter: 0.2em,
  table.hline(stroke: 0.08em),
  [], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]],
  table.hline(stroke: 0.03em, start: 1, end: 2),
  table.hline(stroke: 0.03em, start: 2, end: 3),
  table.hline(stroke: 0.03em, start: 3, end: 4),
  table.hline(stroke: 0.03em, start: 4, end: 5),
  [], [(1)], [(2)], [(3)], [(4)],
  table.hline(stroke: 0.05em),
  table.hline(stroke: 0.03em),
  [post], [0.026\*\*\* \ (0.008)], [0.025\*\*\* \ (0.008)], [0.026\*\*\* \ (0.008)], [0.025\*\*\* \ (0.008)],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [gvkey], [x], [x], [x], [x],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [Sample], [All], [All], [Switchers], [Switchers],
  [Observations], [28,230], [23,923], [3,611], [3,154],
  [$R^2$], [0.664], [0.702], [0.619], [0.657],
  table.hline(stroke: 0.08em),
  [#table.cell(colspan: 5)[#text(size: 10pt)[Significance levels: \* p \< 0.1, \*\* p \< 0.05, \*\*\* p \< 0.01. Format of coefficient cell: Coefficient   (Std. Error)]]],
)
], caption: figure.caption(
position: top, 
[
Effect of IDD adoption: No year fixed effects
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-no-year-fe>


#emph[What does this tell you about what drives the regression results in this setting?]

Regression results are driven by the switchers.

#emph[What does this tell you about the role of the "non-switchers" (i.e., firms not in the #NormalTok("switchers"); data frame) in the regression?]

This tells us that the only impact of the "non-switchers" on the full regression results is via their effect on the estimated year fixed effects. These firms do not directly affect the estimates of the treatment effect or of other firms' fixed effects, which are driven by the switchers and the individual firms, respectively.

#block[
#set enum(numbering: "1.", start: 4)
+ Would you expect the inclusion of controls (see the question above) to have a significant impact on the regression results? Why or why not?
]

I would not expect the controls to have a big impact for a number of reasons. First, many controls would be fairly persistent over time and, with firm fixed effects included, only within-firm variation in controls that is correlated with the treatment indicator (i.e., #NormalTok("POST"); for treatment firms) will affect the estimated effects.

With firm fixed effects, only within-firm variation in controls can change the treatment estimate. Persistence makes a small effect plausible when the remaining variation is weakly related to treatment, but it is not a guarantee. A time-varying omitted confounder can still matter. State effects provide a useful sensitivity check because firms sometimes change headquarters state; the paper includes state effects in its specification. When making that comparison, hold the estimation sample and covariance convention fixed first, so that changes in the coefficient are not confused with changes in the sample or standard errors.

#block[
#set enum(numbering: "1.", start: 5)
+ What differs between the regressions reported in columns (1) and (3), and (2) and (4) of #ref(<tbl-idd-by-year>, supplement: [Table]), respectively? What happens if you omit the year fixed effects from both sets of regressions? What does this tell you about what drives the regression results in this setting?
]

#figure([
#table(
  columns: (auto, 1fr, 1fr, 1fr, 1fr), align: (left, center, center, center, center),
  column-gutter: (0em, 0.5em, 0.5em, 0.5em),
  stroke: none, row-gutter: 0.2em,
  table.hline(stroke: 0.08em),
  [], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]],
  table.hline(stroke: 0.03em, start: 1, end: 2),
  table.hline(stroke: 0.03em, start: 2, end: 3),
  table.hline(stroke: 0.03em, start: 3, end: 4),
  table.hline(stroke: 0.03em, start: 4, end: 5),
  [], [(1)], [(2)], [(3)], [(4)],
  table.hline(stroke: 0.05em),
  table.hline(stroke: 0.03em),
  [t = -5], [-0.004 \ (0.019)], [0.001 \ (0.021)], [-0.017 \ (0.027)], [-0.009 \ (0.029)],
  [t = -4], [-0.018 \ (0.022)], [-0.031 \ (0.023)], [-0.026 \ (0.025)], [-0.038 \ (0.026)],
  [t = -3], [-0.03 \ (0.02)], [-0.029 \ (0.02)], [-0.031 \ (0.021)], [-0.031 \ (0.022)],
  [t = -2], [-0.009 \ (0.018)], [-0.003 \ (0.018)], [-0.014 \ (0.019)], [-0.01 \ (0.019)],
  [t = 0], [-0.000882 \ (0.015)], [0.016 \ (0.015)], [0.007 \ (0.016)], [0.02 \ (0.017)],
  [t = 1], [0.009 \ (0.016)], [0.025 \ (0.017)], [0.021 \ (0.018)], [0.031 \ (0.02)],
  [t = 2], [-0.008 \ (0.017)], [0.01 \ (0.018)], [0.009 \ (0.021)], [0.017 \ (0.023)],
  [t = 3], [0.023 \ (0.019)], [0.021 \ (0.02)], [0.038 \ (0.025)], [0.026 \ (0.027)],
  [t = 4], [0.028 \ (0.019)], [0.039\* \ (0.021)], [0.041 \ (0.027)], [0.042 \ (0.03)],
  [t = 5], [0.043\*\*\* \ (0.015)], [0.048\*\*\* \ (0.016)], [0.046 \ (0.032)], [0.039 \ (0.036)],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [gvkey], [x], [x], [x], [x],
  [year], [x], [x], [x], [x],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [Sample], [All], [All], [Switchers], [Switchers],
  [Observations], [28,230], [23,923], [3,104], [2,732],
  [$R^2$], [0.666], [0.703], [0.624], [0.667],
  table.hline(stroke: 0.08em),
  [#table.cell(colspan: 5)[#text(size: 10pt)[Significance levels: \* p \< 0.1, \*\* p \< 0.05, \*\*\* p \< 0.01. Format of coefficient cell: Coefficient   (Std. Error)]]],
)
], caption: figure.caption(
position: top, 
[
Effect of IDD adoption by year
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-idd-by-year>


#emph[What happens if you omit the year fixed effects from both sets of regressions?]

Here is the code to estimate regressions without year fixed effects.

#block[
#Skylighting(([#NormalTok("fms_year_no_year ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ C(t, Treatment(reference=-1)) | gvkey\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ C(t, Treatment(reference=-1)) | gvkey\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ C(t, Treatment(reference=-1)) | gvkey\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t.");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"t\"");#NormalTok(").is_finite()), vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ C(t, Treatment(reference=-1)) | gvkey\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t.");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"t\"");#NormalTok(").is_finite()), vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("]");],));
]
As can be seen in the results reported in #ref(<tbl-by-year>, supplement: [Table]), only the firms that are treated for part of the sample drive the regression results absent year fixed effects. We have identical coefficients in columns (1) and (3), and in columns (2) and (4).

#figure([
#table(
  columns: (auto, 1fr, 1fr, 1fr, 1fr), align: (left, center, center, center, center),
  column-gutter: (0em, 0.5em, 0.5em, 0.5em),
  stroke: none, row-gutter: 0.2em,
  table.hline(stroke: 0.08em),
  [], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]],
  table.hline(stroke: 0.03em, start: 1, end: 2),
  table.hline(stroke: 0.03em, start: 2, end: 3),
  table.hline(stroke: 0.03em, start: 3, end: 4),
  table.hline(stroke: 0.03em, start: 4, end: 5),
  [], [(1)], [(2)], [(3)], [(4)],
  table.hline(stroke: 0.05em),
  table.hline(stroke: 0.03em),
  [t = -5], [-0.012 \ (0.019)], [0.003 \ (0.02)], [-0.012 \ (0.019)], [0.003 \ (0.021)],
  [t = -4], [-0.03 \ (0.022)], [-0.035 \ (0.023)], [-0.03 \ (0.022)], [-0.035 \ (0.023)],
  [t = -3], [-0.04\*\* \ (0.02)], [-0.033 \ (0.02)], [-0.04\* \ (0.02)], [-0.033 \ (0.021)],
  [t = -2], [-0.013 \ (0.018)], [-0.005 \ (0.018)], [-0.013 \ (0.018)], [-0.005 \ (0.018)],
  [t = 0], [0.005 \ (0.015)], [0.019 \ (0.015)], [0.005 \ (0.015)], [0.019 \ (0.015)],
  [t = 1], [0.018 \ (0.016)], [0.028\* \ (0.017)], [0.018 \ (0.016)], [0.028\* \ (0.017)],
  [t = 2], [0.004 \ (0.017)], [0.011 \ (0.018)], [0.004 \ (0.017)], [0.011 \ (0.018)],
  [t = 3], [0.033\* \ (0.018)], [0.02 \ (0.02)], [0.033\* \ (0.019)], [0.02 \ (0.02)],
  [t = 4], [0.035\* \ (0.019)], [0.032 \ (0.021)], [0.035\* \ (0.02)], [0.032 \ (0.021)],
  [t = 5], [0.045\*\*\* \ (0.014)], [0.032\*\* \ (0.015)], [0.045\*\*\* \ (0.014)], [0.032\*\* \ (0.015)],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [gvkey], [x], [x], [x], [x],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [Sample], [All], [All], [Switchers], [Switchers],
  [Observations], [28,230], [23,923], [3,104], [2,732],
  [$R^2$], [0.664], [0.702], [0.62], [0.665],
  table.hline(stroke: 0.08em),
  [#table.cell(colspan: 5)[#text(size: 10pt)[Significance levels: \* p \< 0.1, \*\* p \< 0.05, \*\*\* p \< 0.01. Format of coefficient cell: Coefficient   (Std. Error)]]],
)
], caption: figure.caption(
position: top, 
[
Effect of IDD adoption by year: No year fixed effects
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-by-year>


#block[
#set enum(numbering: "1.", start: 6)
+ What patterns do you observe in the coefficients reported in #ref(<tbl-idd-by-year>, supplement: [Table])? Do these conform to what you would expect from #cite(<Li:2018tj>, form: "prose")? (It may be easiest to focus on these in groups, e.g., those in $t - 5$ to $t - 2$, those in $t + 0$ to $t + 3$ and those for $t + 4$ and $t + 5$.)
]

In #ref(<tbl-idd-by-year>, supplement: [Table]), most pre-adoption coefficients are negative, while the clearest positive signal in the full sample is in the pooled $t + 5$-and-later bin. The weighted measure is only marginally significant at $t + 4$\; results for firms observed to switch differ. The estimates and their uncertainty should be read together, rather than treating a sign as evidence of a nonzero effect.

These do #emph[not] conform with what I'd expect from reading #cite(<Li:2018tj>, form: "prose"). First, the negative coefficients in years $t - 5$ through $t - 2$ are problematic, but their signs alone do not establish anticipation or rejection of parallel trends. Their uncertainty and a joint test of the leads should also be examined. Second, the clearest positive signals appear relatively late in this expanded specification. #cite(<Li:2018tj>, form: "prose") discuss effects within one or two years \[pp.~269 and 288\], so it is inaccurate to say that the paper does not discuss delay. Table 3 pools observations from $t + 2$ onward and cannot identify onset within that pooled period. Online appendix Table OA2 uses a $\[ - 2 \, + 2 \]$ window and reports significant coefficients at exactly $t + 2$, with a matched sample and a different reference year. Our later pattern is a discrepancy to investigate, rather than a direct contradiction of estimates from that different design.

The number and composition of firms vary by event year. The later coefficients rely on fewer firms, and a pooled tail can contain several observations from each firm. Report firm counts as well as row counts before judging how much independent support a late-period estimate has.

#block[
#set enum(numbering: "1.", start: 7)
+ How do the variables in #ref(<tbl-idd-by-year>, supplement: [Table]) differ from those used in Table 3 of #cite(<Li:2018tj>, form: "prose")? Modify the code above (e.g., #NormalTok("format_event_time()");) to produce analysis closer to that reported in Table 3 of #cite(<Li:2018tj>, form: "prose").
]

#cite(<Li:2018tj>, form: "prose") treat years before $t - 2$ the same as years without treatment and collapse years after $t + 2$ into year $t + 2$. We can replace the regression above by using a modified #NormalTok("format_event_time()"); as follows. This function pools the years before $t - 2$ with the control firms by setting their level at $- oo$ and caps the upper event-time indicator at $t + 2$.

The other thing that #cite(<Li:2018tj>, form: "prose") do is report coefficients relative to non-treatment firms and firm-years strictly before $t - 2$ (#emph[some] reference group needs to be chosen), which we implement by pooling pre-$t - 2$ treated firm-years with the control group.

#block[
#Skylighting(([#KeywordTok("def");#NormalTok(" format_event_time_llz(value):");],
[#NormalTok("    ");#ControlFlowTok("if");#NormalTok(" value ");#KeywordTok("is");#NormalTok(" ");#VariableTok("None");#NormalTok(" ");#KeywordTok("or");#NormalTok(" value ");#OperatorTok("<");#NormalTok(" ");#OperatorTok("-");#DecValTok("2");#NormalTok(":");],
[#NormalTok("        ");#ControlFlowTok("return");#NormalTok(" ");#OperatorTok("-");#NormalTok("np.inf");],
[#NormalTok("    value ");#OperatorTok("=");#NormalTok(" ");#BuiltInTok("int");#NormalTok("(value)");],
[#NormalTok("    ");#ControlFlowTok("return");#NormalTok(" ");#BuiltInTok("float");#NormalTok("(");#BuiltInTok("min");#NormalTok("(");#DecValTok("2");#NormalTok(", value))");],
[],
[#NormalTok("reg_data_t_llz ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    reg_data");],
[#NormalTok("    .join(switch_years, on");#OperatorTok("=");#StringTok("\"gvkey\"");#NormalTok(", how");#OperatorTok("=");#StringTok("\"left\"");#NormalTok(")");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        (pl.col(");#StringTok("\"year\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"adoption_year\"");#NormalTok("))");],
[#NormalTok("        .map_elements(");],
[#NormalTok("            format_event_time_llz,");],
[#NormalTok("            return_dtype");#OperatorTok("=");#NormalTok("pl.Float64,");],
[#NormalTok("            skip_nulls");#OperatorTok("=");#VariableTok("False");#NormalTok(",");],
[#NormalTok("        )");],
[#NormalTok("        .alias(");#StringTok("\"t_llz\"");#NormalTok("),");],
[#NormalTok("    )");],
[#NormalTok(")");],
[],
[#NormalTok("fms_llz ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ C(t_llz, Treatment(reference=-np.inf)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t_llz, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ C(t_llz, Treatment(reference=-np.inf)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t_llz, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("]");],));
]
#figure([
#table(
  columns: (auto, 1fr, 1fr), align: (left, center, center),
  column-gutter: (0em, 0.5em),
  stroke: none, row-gutter: 0.2em,
  table.hline(stroke: 0.08em),
  [], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]],
  table.hline(stroke: 0.03em, start: 1, end: 2),
  table.hline(stroke: 0.03em, start: 2, end: 3),
  [], [(1)], [(2)],
  table.hline(stroke: 0.05em),
  table.hline(stroke: 0.03em),
  [t = -2], [0.008 \ (0.017)], [0.015 \ (0.017)],
  [t = -1], [0.016 \ (0.015)], [0.018 \ (0.016)],
  [t = 0], [0.015 \ (0.014)], [0.034\*\* \ (0.015)],
  [t = 1], [0.024 \ (0.016)], [0.043\*\* \ (0.017)],
  [t = 2], [0.042\*\*\* \ (0.013)], [0.05\*\*\* \ (0.014)],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [gvkey], [x], [x],
  [year], [x], [x],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [Observations], [28,230], [23,923],
  [$R^2$], [0.665], [0.703],
  table.hline(stroke: 0.08em),
  [#table.cell(colspan: 3)[#text(size: 10pt)[Significance levels: \* p \< 0.1, \*\* p \< 0.05, \*\*\* p \< 0.01. Format of coefficient cell: Coefficient   (Std. Error)]]],
)
], caption: figure.caption(
position: top, 
[
Effect of IDD adoption by year
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-by-year2>


The positive pooled coefficients in #ref(<tbl-by-year2>, supplement: [Table]) have the same broad direction as Table 3 of #cite(<Li:2018tj>, form: "prose"). These regressions retain IID standard errors and change the event coding only, so their significance cannot be described as stronger evidence than the paper's differently clustered specification. The net effect of the reporting choices made here appears to be to collapse the effects of $t + 3$, $t + 4$, and $t + 5$ into $t + 2$ and to suppress the reporting of any of the awkward negative coefficients in years $t - 5$ through $t - 3$.

This changes the event coding, but it does not reproduce the paper's full specification. We retain the book's controls, missing-value handling and first observed pre-to-post transition as the event year. That transition can reflect a headquarters change or an observation gap, whereas the paper's indicators refer to state adoption years. The authors' supplied code replaces missing weighted ratios with one; our code retains them as missing. State effects, state-clustered inference and sample restrictions are further distinct choices.

A significant coefficient on the pooled $t + 2$-and-later category does not establish that an effect begins at exactly $t + 2$. It averages the later years too, while pooling early years into the reference removes their separate estimates from view. Assess the displayed comparison with these differences in mind.

#block[
#set enum(numbering: "1.", start: 8)
+ The #NormalTok("format_event_time()"); function collapses years after $t + 5$ and before $t - 5$ into years $t + 5$ and $t - 5$, respectively. When would this approach make sense? What would be one alternative approach to handling these years? Does your suggested approach make a difference in this setting?
]

Binning can make sense when very early and late event years contain few observations, so separate estimates would be unstable and hard to interpret. Pooling gives more precise tail estimates, but imposes a common effect on all years in each tail. It is most defensible when that approximation is plausible and the research question concerns the years near adoption. It can conceal changes or reversals in distant years, so the bin definitions and sensitivity to them should be reported.

One alternative approach would be not to collapse them at all and report them separately. Here we use the #NormalTok("format_event_time_all()"); function defined above, which implements this idea.

#block[
#Skylighting(([#KeywordTok("def");#NormalTok(" format_event_time_all(value):");],
[#NormalTok("    ");#ControlFlowTok("if");#NormalTok(" value ");#KeywordTok("is");#NormalTok(" ");#VariableTok("None");#NormalTok(":");],
[#NormalTok("        ");#ControlFlowTok("return");#NormalTok(" ");#OperatorTok("-");#NormalTok("np.inf");],
[#NormalTok("    ");#ControlFlowTok("return");#NormalTok(" ");#BuiltInTok("float");#NormalTok("(");#BuiltInTok("int");#NormalTok("(value))");],
[],
[#NormalTok("reg_data_t_all ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    reg_data");],
[#NormalTok("    .join(switch_years, on");#OperatorTok("=");#StringTok("\"gvkey\"");#NormalTok(", how");#OperatorTok("=");#StringTok("\"left\"");#NormalTok(")");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        (pl.col(");#StringTok("\"year\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"adoption_year\"");#NormalTok("))");],
[#NormalTok("        .map_elements(");],
[#NormalTok("            format_event_time_all,");],
[#NormalTok("            return_dtype");#OperatorTok("=");#NormalTok("pl.Float64,");],
[#NormalTok("            skip_nulls");#OperatorTok("=");#VariableTok("False");#NormalTok(",");],
[#NormalTok("        )");],
[#NormalTok("        .alias(");#StringTok("\"t_all\"");#NormalTok("),");],
[#NormalTok("    )");],
[#NormalTok(")");],
[],
[#NormalTok("fms_all_years ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ C(t_all, Treatment(reference=-1)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t_all, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ C(t_all, Treatment(reference=-1)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t_all, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ C(t_all, Treatment(reference=-1)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t_all.");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"t_all\"");#NormalTok(").is_finite()), vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ C(t_all, Treatment(reference=-1)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t_all.");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"t_all\"");#NormalTok(").is_finite()), vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("]");],));
]
#figure([
#block[
#set text(size: 8pt)
#table(
  columns: (auto, 1fr, 1fr, 1fr, 1fr), align: (left, center, center, center, center),
  column-gutter: (0em, 0.5em, 0.5em, 0.5em),
  stroke: none, row-gutter: 0em,
  table.hline(stroke: 0.08em),
  [], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]],
  table.hline(stroke: 0.03em, start: 1, end: 2),
  table.hline(stroke: 0.03em, start: 2, end: 3),
  table.hline(stroke: 0.03em, start: 3, end: 4),
  table.hline(stroke: 0.03em, start: 4, end: 5),
  [], [(1)], [(2)], [(3)], [(4)],
  table.hline(stroke: 0.05em),
  table.hline(stroke: 0.03em),
  [t = -15], [0.317\*\*], [0.23], [0.242], [0.177],
  [t = -14], [0.261], [0.088], [0.239], [0.073],
  [t = -13], [-0.026], [], [-0.08], [],
  [t = -12], [-0.471\*\*], [], [-0.529], [],
  [t = -11], [-0.227\*\*\*], [-0.21\*\*\*], [-0.255], [-0.24],
  [t = -10], [-0.128\*\*], [-0.153\*\*], [-0.147], [-0.165],
  [t = -9], [-0.072], [-0.067], [-0.088], [-0.083],
  [t = -8], [-0.009], [0.064], [-0.022], [0.051],
  [t = -7], [0.117\*\*\*], [0.16\*\*\*], [0.096], [0.139],
  [t = -6], [0.034], [0.037], [0.014], [0.017],
  [t = -5], [-0.025], [-0.036], [-0.045], [-0.057],
  [t = -4], [-0.018], [-0.032], [-0.031], [-0.046],
  [t = -3], [-0.03], [-0.03], [-0.034], [-0.036],
  [t = -2], [-0.008], [-0.003], [-0.017], [-0.013],
  [t = 0], [-0.001], [0.016], [0.007], [0.021],
  [t = 1], [0.008], [0.025], [0.023], [0.036],
  [t = 2], [-0.008], [0.011], [0.013], [0.025],
  [t = 3], [0.022], [0.022], [0.043], [0.035],
  [t = 4], [0.027], [0.039\*], [0.047], [0.053],
  [t = 5], [0.04\*], [0.037\*], [0.063], [0.054],
  [t = 6], [0.029], [0.041\*], [0.047], [0.052],
  [t = 7], [0.05\*\*], [0.053\*\*], [0.061], [0.062],
  [t = 8], [0.054\*\*], [0.057\*\*], [0.068], [0.068],
  [t = 9], [0.042\*], [0.028], [0.047], [0.029],
  [t = 10], [0.039], [0.04], [0.042], [0.041],
  [t = 11], [0.077\*\*], [0.099\*\*\*], [0.082], [0.095],
  [t = 12], [0.072\*\*], [0.097\*\*], [0.071], [0.09],
  [t = 13], [0.05], [0.097\*], [0.055], [0.093],
  [t = 14], [-0.033], [-0.04], [-0.033], [-0.05],
  [t = 15], [-0.011], [0.058], [-0.016], [0.037],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [gvkey], [x], [x], [x], [x],
  [year], [x], [x], [x], [x],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [Sample], [All], [All], [Switchers], [Switchers],
  [Observations], [28,230], [23,923], [3,104], [2,732],
  [$R^2$], [0.666], [0.704], [0.63], [0.673],
  table.hline(stroke: 0.08em),
  [#table.cell(colspan: 5)[#text(size: 10pt)[Significance levels: \* p \< 0.1, \*\* p \< 0.05, \*\*\* p \< 0.01. Format of coefficient cell: Coefficient]]],
)
]
], caption: figure.caption(
position: top, 
[
Effect of IDD adoption by year (all years)
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-by-year-all>


But, as can be seen in the results reported in #ref(<tbl-by-year-all>, supplement: [Table]), this level of transparency makes the results seem even more difficult to explain.#footnote[Note that the results obtained from running the equivalent code in R differ for columns (3) and (4) because the R code omits the $t + 15$ indicator due to collinearity and the Python code makes a different choice. This has no impact on the substance of the results.]

#block[
#set enum(numbering: "1.", start: 9)
+ How helpful do you find #ref(<fig-coefs-by-year>, supplement: [Figure]) (plot of the coefficients by year)?
]

#Skylighting(([#NormalTok("plot_coefs(fms_year[");#DecValTok("0");#NormalTok("])");],));
#figure([
#box(image("panel-data-solutions-polars_files/figure-typst/fig-coefs-by-year-output-1.svg", alt: "Plot shows estimated coefficients by year and that, while coefficients tend to be positive for period after year zero, only in year 5 do these become statistically distinguishable from zero. In fact, in year 2 the coefficient is below zero. Year -1 is the baseline (so is zero with no standard errors)."))
], caption: figure.caption(
position: bottom, 
[
Plot of coefficients by year
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-coefs-by-year>


It's somewhat helpful, but it's really just the "by year" regression results in graphical form. I'm not inclined to believe any of the results in #cite(<Li:2018tj>, form: "prose") given where these results are coming from … and I don't need the plot to tell me that. I think that if the results were (in my view, counterfactually) real, a plot like this might be a useful way to communicate that.

#block[
#set enum(numbering: "1.", start: 10)
+ Describe the data set created from the following code. What proportion of the firms in the data set have #NormalTok("same_state"); equal to #NormalTok("true");? For the purposes of empirical analysis, do the firms with #NormalTok("same_state"); equal to #NormalTok("false"); enhance, or detract from, our ability to draw causal inferences about the effect of adoption of IDD?
]

#Skylighting(([#NormalTok("switch_years_state ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    reg_data_switchers");],
[#NormalTok("    .sort([");#StringTok("\"gvkey\"");#NormalTok(", ");#StringTok("\"datadate\"");#NormalTok("])");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        pl.col(");#StringTok("\"state\"");#NormalTok(", ");#StringTok("\"period_type\"");#NormalTok(").shift(");#DecValTok("1");#NormalTok(").over(");#StringTok("\"gvkey\"");#NormalTok(")");],
[#NormalTok("        .name.prefix(");#StringTok("\"lag_\"");#NormalTok(")");],
[#NormalTok("    )");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        same_state");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"state\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" pl.col(");#StringTok("\"lag_state\"");#NormalTok("),");],
[#NormalTok("        adoption_year");#OperatorTok("=");],
[#NormalTok("            (pl.col(");#StringTok("\"period_type\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" ");#StringTok("\"Post-adoption\"");#NormalTok(") ");#OperatorTok("&");],
[#NormalTok("            (pl.col(");#StringTok("\"lag_period_type\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" ");#StringTok("\"Pre-adoption\"");#NormalTok("),");],
[#NormalTok("    )");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"adoption_year\"");#NormalTok("))");],
[#NormalTok(")");],
[],
[#NormalTok("switch_years_state.group_by(");#StringTok("\"same_state\"");#NormalTok(").agg(n");#OperatorTok("=");#NormalTok("pl.");#BuiltInTok("len");#NormalTok("())");],));
#table(
  columns: 2,
  align: (auto,auto,),
  table.header([same\_state], [n],
    [bool], [u32],),
  table.hline(),
  [false], [134],
  [true], [251],
)
A firm can contribute more than one observed pre-to-post transition, so the proportion of records is not necessarily the proportion of firms. The following calculation distinguishes all transition records, firms with at least one unchanged-state transition, and each firm's first transition.

#Skylighting(([#NormalTok("firm_transitions ");#OperatorTok("=");#NormalTok(" switch_years_state.group_by(");#StringTok("\"gvkey\"");#NormalTok(").agg(");],
[#NormalTok("    any_same_state");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"same_state\"");#NormalTok(").fill_null(");#VariableTok("False");#NormalTok(").");#BuiltInTok("any");#NormalTok("()");],
[#NormalTok(")");],
[#NormalTok("first_transitions ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    switch_years_state.sort([");#StringTok("\"gvkey\"");#NormalTok(", ");#StringTok("\"datadate\"");#NormalTok("])");],
[#NormalTok("    .unique(");#StringTok("\"gvkey\"");#NormalTok(", keep");#OperatorTok("=");#StringTok("\"first\"");#NormalTok(", maintain_order");#OperatorTok("=");#VariableTok("True");#NormalTok(")");],
[#NormalTok(")");],
[#NormalTok("state_transition_summary ");#OperatorTok("=");#NormalTok(" pl.DataFrame({");],
[#NormalTok("    ");#StringTok("\"Unit\"");#NormalTok(": [");#StringTok("\"Transition records\"");#NormalTok(", ");#StringTok("\"Firms: at least one\"");#NormalTok(", ");#StringTok("\"Firms: first transition\"");#NormalTok("],");],
[#NormalTok("    ");#StringTok("\"Unchanged state\"");#NormalTok(": [");],
[#NormalTok("        switch_years_state[");#StringTok("\"same_state\"");#NormalTok("].");#BuiltInTok("sum");#NormalTok("(),");],
[#NormalTok("        firm_transitions[");#StringTok("\"any_same_state\"");#NormalTok("].");#BuiltInTok("sum");#NormalTok("(),");],
[#NormalTok("        first_transitions[");#StringTok("\"same_state\"");#NormalTok("].");#BuiltInTok("sum");#NormalTok("(),");],
[#NormalTok("    ],");],
[#NormalTok("    ");#StringTok("\"Total\"");#NormalTok(": [");],
[#NormalTok("        switch_years_state.height,");],
[#NormalTok("        firm_transitions.height,");],
[#NormalTok("        first_transitions.height,");],
[#NormalTok("    ],");],
[#NormalTok("}).with_columns(Share");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"Unchanged state\"");#NormalTok(") ");#OperatorTok("/");#NormalTok(" pl.col(");#StringTok("\"Total\"");#NormalTok("))");],
[#NormalTok("state_transition_summary.style.fmt_integer(");],
[#NormalTok("    columns");#OperatorTok("=");#NormalTok("[");#StringTok("\"Unchanged state\"");#NormalTok(", ");#StringTok("\"Total\"");#NormalTok("]");],
[#NormalTok(").fmt_percent(columns");#OperatorTok("=");#StringTok("\"Share\"");#NormalTok(", decimals");#OperatorTok("=");#DecValTok("1");#NormalTok(")");],));
#{set text(font: ("Libertinus Serif",) , size: 10pt); table(
  columns: 4,
  align: (left,right,right,right,),
  table.header(table.cell(align: bottom + left, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); Unit], table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); Unchanged state], table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); Total], table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); Share],),
  table.hline(),
  table.cell(align: horizon + left)[Transition records], table.cell(align: horizon + right)[251], table.cell(align: horizon + right)[385], table.cell(align: horizon + right)[65.2%],
  table.cell(align: horizon + left)[Firms: at least one], table.cell(align: horizon + right)[251], table.cell(align: horizon + right)[382], table.cell(align: horizon + right)[65.7%],
  table.cell(align: horizon + left)[Firms: first transition], table.cell(align: horizon + right)[250], table.cell(align: horizon + right)[382], table.cell(align: horizon + right)[65.4%],
)}
#NormalTok("same_state"); is #NormalTok("true"); when the headquarters state is unchanged from the preceding observed record and #NormalTok("false"); when the transition coincides with a recorded state change. The first-transition calculation follows the book's event-year convention; the “at least one” calculation answers a different firm-level question.

The changed-state cases weaken the claim that every exposure change comes from an exogenous court ruling in a firm's existing state. They can reflect endogenous relocation, but location-record changes, mergers and other events may also explain them; these records alone do not establish intentional relocation. They may add statistical variation while making causal interpretation harder. Useful sensitivity checks restrict transitions to unchanged-state firms or fix headquarters location before the ruling, while acknowledging the resulting selection and measurement issues.

#block[
#set enum(numbering: "1.", start: 11)
+ What issues might be implied by the following data? How might you address these?
]

#Skylighting(([#NormalTok("(");],
[#NormalTok("    reg_data_t");],
[#NormalTok("    .group_by(");#StringTok("\"t\"");#NormalTok(")");],
[#NormalTok("    .agg(n");#OperatorTok("=");#NormalTok("pl.");#BuiltInTok("len");#NormalTok("().alias(");#StringTok("\"n\"");#NormalTok("))");],
[#NormalTok("    .sort(");#StringTok("\"t\"");#NormalTok(")");],
[#NormalTok("    .style");],
[#NormalTok("    .fmt_integer()");],
[#NormalTok(")");],));
#{set text(font: ("Libertinus Serif",) , size: 10pt); table(
  columns: 2,
  align: (right,right,),
  table.header(table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); t], table.cell(align: bottom + right, fill: rgb("#ffffff"))[#set text(size: 1.0em , weight: "regular" , fill: rgb("#333333")); n],),
  table.hline(),
  table.cell(align: horizon + right)[−inf], table.cell(align: horizon + right)[25,603],
  table.cell(align: horizon + right)[−5], table.cell(align: horizon + right)[232],
  table.cell(align: horizon + right)[−4], table.cell(align: horizon + right)[116],
  table.cell(align: horizon + right)[−3], table.cell(align: horizon + right)[153],
  table.cell(align: horizon + right)[−2], table.cell(align: horizon + right)[218],
  table.cell(align: horizon + right)[−1], table.cell(align: horizon + right)[321],
  table.cell(align: horizon + right)[0], table.cell(align: horizon + right)[384],
  table.cell(align: horizon + right)[1], table.cell(align: horizon + right)[305],
  table.cell(align: horizon + right)[2], table.cell(align: horizon + right)[233],
  table.cell(align: horizon + right)[3], table.cell(align: horizon + right)[192],
  table.cell(align: horizon + right)[4], table.cell(align: horizon + right)[168],
  table.cell(align: horizon + right)[5], table.cell(align: horizon + right)[782],
)}
One issue is that the sample is changing from one event-period to the next. Requiring observation at $t + 4$ does not ensure a balanced panel at all earlier event times, and it excludes the never-switching comparison pool. A balanced-window sensitivity analysis must explicitly require each desired event year and separately retain an appropriate control pool. One idea would be to require that a firm be in the sample in $t + 4$ (the full and switcher samples play different roles once year effects are included) and to drop all periods after $t + 4$ and run the by-year regressions for this sample.

#block[
#Skylighting(([#NormalTok("reg_data_t2 ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    reg_data_t");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"t\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" ");#DecValTok("4");#NormalTok(")");],
[#NormalTok("    .select(");#StringTok("\"gvkey\"");#NormalTok(")");],
[#NormalTok("    .unique()");],
[#NormalTok("    .join(reg_data_t, on");#OperatorTok("=");#StringTok("\"gvkey\"");#NormalTok(", how");#OperatorTok("=");#StringTok("\"inner\"");#NormalTok(")");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"t\"");#NormalTok(") ");#OperatorTok("<");#NormalTok(" ");#DecValTok("5");#NormalTok(")");],
[#NormalTok(")");],
[],
[#NormalTok("fms_constant ");#OperatorTok("=");#NormalTok(" [");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio ~ C(t, Treatment(reference=-1)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t2, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("    pf.feols(");#StringTok("\"ln_ratio_sale ~ C(t, Treatment(reference=-1)) \"");],
[#NormalTok("             ");#StringTok("\"| gvkey + year\"");#NormalTok(",");],
[#NormalTok("             data");#OperatorTok("=");#NormalTok("reg_data_t2, vcov");#OperatorTok("=");#StringTok("\"iid\"");#NormalTok("),");],
[#NormalTok("]");],));
]
Using the code above to create this sample, regression results are reported in #ref(<tbl-by-year-constant>, supplement: [Table]). Perhaps unsurprisingly there are no consistent results here.

#figure([
#table(
  columns: (auto, 1fr, 1fr), align: (left, center, center),
  column-gutter: (0em, 0.5em),
  stroke: none, row-gutter: 0.2em,
  table.hline(stroke: 0.08em),
  [], [#table.cell(colspan: 1)[ln\_ratio]], [#table.cell(colspan: 1)[ln\_ratio\_sale]],
  table.hline(stroke: 0.03em, start: 1, end: 2),
  table.hline(stroke: 0.03em, start: 2, end: 3),
  [], [(1)], [(2)],
  table.hline(stroke: 0.05em),
  table.hline(stroke: 0.03em),
  [t = -5], [-0.011 \ (0.081)], [-0.147 \ (0.095)],
  [t = -4], [-0.026 \ (0.055)], [-0.105 \ (0.064)],
  [t = -3], [-0.036 \ (0.041)], [-0.084\* \ (0.047)],
  [t = -2], [-0.004 \ (0.03)], [-0.038 \ (0.033)],
  [t = 0], [0.015 \ (0.027)], [0.055\* \ (0.03)],
  [t = 1], [0.028 \ (0.037)], [0.087\*\* \ (0.043)],
  [t = 2], [-0.014 \ (0.049)], [0.064 \ (0.059)],
  [t = 3], [-0.023 \ (0.062)], [0.076 \ (0.075)],
  [t = 4], [-0.018 \ (0.075)], [0.112 \ (0.092)],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [gvkey], [x], [x],
  [year], [x], [x],
  table.hline(stroke: 0.03em),
  table.hline(stroke: 0.03em),
  [Observations], [1,237], [1,126],
  [$R^2$], [0.667], [0.693],
  table.hline(stroke: 0.08em),
  [#table.cell(colspan: 3)[#text(size: 10pt)[Significance levels: \* p \< 0.1, \*\* p \< 0.05, \*\*\* p \< 0.01. Format of coefficient cell: Coefficient   (Std. Error)]]],
)
], caption: figure.caption(
position: top, 
[
Effect of IDD adoption by year: Firms observed at $t + 4$
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-by-year-constant>


The $t + 4$ restriction also selects on later survival and data availability. A fully balanced event window would require exactly one complete observation in every chosen event year for both outcomes, then retain an appropriate comparison pool. Report the number of qualifying treated firms and support by adoption cohort: balancing can sharply reduce the available sample. Neither balancing nor the selected $t + 4$ sample resolves heterogeneous treatment effects in a staggered-adoption design. The changing sample, a sample selected at $t + 4$, and a balanced-window sample answer different questions.

#pagebreak(weak: true)
= References
<references>
#block[
] <refs>



#set bibliography(style: "linkedin-solutions.csl")

#bibliography(("linkedin-solutions-references.bib"))

