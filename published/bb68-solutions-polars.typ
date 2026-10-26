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
  title: [Solutions for Ball and Brown (1968)],
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

These solutions accompany the #link("https://iangow.github.io/era_pl_book/bb68.html")[Ball and Brown (1968) chapter] of #emph[Empirical Research in Accounting: Tools and Methods]. This notes edition updates the solutions discussed in the original 2026-05-12 post with subsequent corrections and clarifications; it is not a facsimile of the original LinkedIn attachment. The calculations were freshly executed on 26 October 2026.

The calculations use a local Parquet repository, with #NormalTok("DATA_DIR"); pointing to that repository. See the book's #link("https://iangow.github.io/era_pl_book/intro.html")[data setup instructions] and the accompanying #link("https://iangow.github.io/notes/published/linkedin-solutions-requirements.txt")[Python requirements]. The QMD uses the existing #NormalTok("era_pl_sols"); Jupyter kernel, whose environment supplies those packages; its code does not import either solutions repository. Changes in the input data or software can change estimates and timings.

= Principal results of #cite(<Ball:1968ub>, form: "prose")
<principal-results-of-ball1968ub>
== Discussion questions
<discussion-questions>
+ What is the research question of #cite(<Ball:1968ub>, form: "prose")? Do you find the paper to be persuasive?

There are a number of possible answers here. One answer is that the paper examines whether accounting numbers are #emph[meaningful] in a way that seems necessary (but not sufficient) for a claim that they are #emph[useful]. This is (by design) a fairly limited question, but one that is counterposed to a claim that accounting numbers are meaningless.

Relative to the limited question that it asks, the evidence in #cite(<Ball:1968ub>, form: "prose") seems quite persuasive.

#block[
#set enum(numbering: "1.", start: 2)
+ What do you notice about the references in #cite(<Ball:1968ub>, form: "prose", supplement: [pp.~177-178])?
]

The striking thing for me is how recent (at that time) most of the references are. Most come from 1964 or later. Clearly this was an exciting time to be doing empirical accounting research.

#block[
#set enum(numbering: "1.", start: 3)
+ Given that "the most fundamental result" of #cite(<Ball:1968ub>, form: "prose") relates to an association or correlation, is it correct to say that the paper provides no evidence on causal linkages? Does this also mean that #cite(<Ball:1968ub>, form: "prose") is a "merely" descriptive paper according to the taxonomy of research papers outlined in #link("https://iangow.github.io/era_pl_book/causal-inf.html")[Chapter 4]? How might the results of #cite(<Ball:1968ub>, form: "prose") be represented in a causal diagram assuming that accounting information is meaningful and markets are efficient? Would an alternative causal diagram be assumed by a critic who viewed accounting information as meaningless?
]

One possible causal diagram is given in #ref(<fig-bb68-dag>, supplement: [Figure]). \
Note that there is no solid directed arrow connecting $X$ and $Y$ here. Clearly, if markets are efficient (so do not respond to useless or meaningless information) then an arrow from $X$ to $Y$ would imply that accounting information is useful.

But arguably #cite(<Ball:1968ub>, form: "prose") only seek to show that accounting information is meaningful in that it is driven by fundamental information in a way that is correlated with how fundamental information affects share prices. This will lead to accounting reporting being associated with stock returns (represented as a dashed line), which is precisely what #cite(<Ball:1968ub>, form: "prose") find.

#figure([
#box(image("bb68-solutions-polars_files/figure-typst/fig-bb68-dag-output-1.svg"))
], caption: figure.caption(
position: bottom, 
[
BB68 causal diagram
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-bb68-dag>


One alternative causal diagram would be #ref(<fig-bb68-dag-alt>, supplement: [Figure]), which has accounting reports directly causing stock returns but having no connection to fundamental information. In an efficient market, reports without connection to fundamental information should have no effect on returns, so finding an association between returns and such reports would imply market inefficiency.

#figure([
#box(image("bb68-solutions-polars_files/figure-typst/fig-bb68-dag-alt-output-1.svg"))
], caption: figure.caption(
position: bottom, 
[
Alternative causal diagram
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-bb68-dag-alt>


Under the taxonomy in #link("https://iangow.github.io/era_pl_book/causal-inf.html")[Chapter 4], I would not classify BB68 as merely descriptive. Its association is used to assess an explanation in which underlying economic information causes both accounting earnings and returns. That is a causal interpretation involving a common cause, even though it does not identify the causal effect of publishing an accounting report on prices. The empirical association by itself cannot establish that particular causal explanation; its force depends on the assumptions about reporting and market efficiency.

#block[
#set enum(numbering: "1.", start: 4)
+ Describe how Figure 1 of #cite(<Ball:1968ub>, form: "prose") supports each of principal results identified by #cite(<Ball:2019wu>, form: "prose").
]

#cite(<Ball:2019wu>, form: "prose", supplement: [p.~414]) identify three main results of #cite(<Ball:1968ub>, form: "prose"): "The most fundamental result was that accounting earnings and stock returns were correlated. … Nevertheless, annual accounting earnings lacked timeliness. … After the earnings announcement month, the API (which cumulated abnormal returns) continued to drift in the same direction."

The first result (correlation) is shown by the divergence of the two lines for each variable in Figure 1. The second result (limited timeliness) is evidenced by most of the separation occurring before $t = 0$. This does not require a literally zero announcement response: much of the information has already been reflected in prices. The third result is evinced by the lines appearing to continue to diverge further after $t = 0$.

#block[
#set enum(numbering: "1.", start: 5)
+ Consider the causal diagrams you created above. Do the results of #cite(<Ball:1968ub>, form: "prose") provide more support for one causal diagram than the other?
]

The results provide more support for the diagram in which accounting reports reflect fundamental information. If accounting reports were unrelated to fundamentals, an efficient market should not price them. The evidence is not a clean causal test, but it is difficult to reconcile with a strong claim that accounting income is meaningless.

#block[
#set enum(numbering: "1.", start: 6)
+ Compare Figure 1 of #cite(<Ball:2019wu>, form: "prose") with Figure 1 of BB68. What is common between the two figures? What is different?
]

Both figures show divergence between good-news and bad-news portfolios, and both show evidence consistent with post-earnings announcement drift. The #cite(<Ball:2019wu>, form: "prose") figure suggests somewhat more information being conveyed around the earnings announcement, while still showing that much of the return movement occurs before the announcement. The #cite(<Ball:2019wu>, form: "prose") lines are also constructed to be mirror images after subtracting their average; the BB68 lines are not.

#block[
#set enum(numbering: "1.", start: 7)
+ What does "less their average" mean in the title of Figure 1 of #cite(<Ball:2019wu>, form: "prose")? What effect does this have on the plot? (Does it make this plot different from Figure 1 of BB68? Is information lost in the process?)
]

It means that, in each period, the average of the two plotted series is subtracted from each series. This centers the plot and makes the lines symmetric. That differs from Figure 1 of BB68 because the separate levels of the good-news and bad-news lines are no longer visible. Some information is lost, as while the transformation preserves the spread, the two original paths are lost.

#block[
#set enum(numbering: "1.", start: 8)
+ #cite(<Ball:2019wu>, form: "prose", supplement: [p.~418]) say "in this replication we address two issues with the BB68 significance tests." Do you understand the points being made here?
]

Clearly, "no" is a possible answer here. If you answered "yes", then hopefully you explained that the statistical significance tests in #cite(<Ball:1968ub>, form: "prose") used $chi^2$ statistics for each month from $t - 11$ to $t + 6$. However, the hypotheses more clearly relate to the pre-announcement, announcement, and post-announcement periods, not to individual months. Hence, the #cite(<Ball:2019wu>, form: "prose") approach of aggregating data from these periods makes sense.

The second difference is that they use randomization inference to evaluate significance. Randomly reassigning news groups constructs an empirical null distribution rather than relying on the original monthly tests. This does not automatically make a test robust to every form of time-series or cross-firm dependence. See the #link("https://iangow.github.io/era_pl_book/natural-revisited.html#fhk-inference")[discussion of randomization inference].

#block[
#set enum(numbering: "1.", start: 9)
+ #cite(<Ball:2019wu>, form: "prose", supplement: [p.~418]) also say "the persistence of PEAD over time is evidence it does not constitute market inefficiency." What do you make of this argument?
]

This is an unconventional argument to be sure. Persistence could mean the anomaly reflects risk, limits to arbitrage, trading costs, or some other rational mechanism. But persistence alone does not establish that PEAD is not an inefficiency. We will return to this topic when we study PEAD in Chapter 14.

#block[
#set enum(numbering: "1.", start: 10)
+ What is the minimum amount of information that our hypothetical genie needs to provide to enable formation of the portfolios underlying #emph[TI], #emph[NI], and #emph[II]? What are the rules for construction of each of these portfolios?
]

#figure([
#table(
  columns: (33.33%, 33.33%, 33.33%),
  align: (auto,auto,auto,),
  table.header([Measure], [Information from the genie], [Rule],),
  table.hline(),
  [#emph[TI]], [The sign of each stock's monthly abnormal return], [Choose the favorable direction separately each month.],
  [#emph[NI]], [The sign of each stock's compounded abnormal return over months $- 11$ through $0$], [Choose a long or short direction once at the start and retain it.],
  [#emph[II] (called #emph[AI] here)], [The sign of each stock's annual income surprise], [Choose the direction once at the start: long for good income news, short for bad news.],
)
], caption: figure.caption(
position: top, 
[
Information and portfolio rules
]), 
kind: "quarto-float-tbl", 
supplement: "Table", 
)
<tbl-bb68-letters>


The relevant returns are abnormal returns, not raw returns. BB68's indexes abstract from market effects and begin with equal amounts assigned to each stock; #emph[II] uses equal initial exposure per firm, rather than allocating one half of the capital to each news group irrespective of their sizes. #emph[TI] allows the direction to change each month, while #emph[NI] and #emph[II] fix it for the 12-month period. As returns accumulate, the values of individual positions can change, so equal initial amounts do not mean equal position values throughout the year. The genie supplies no magnitudes or rankings needed to optimize unequal initial allocations. For #emph[II], the income information must be supplied before the investment window, making this an informational thought experiment rather than a feasible trading strategy.

#block[
#set enum(numbering: "1.", start: 11)
+ #cite(<Ball:1968ub>, form: "prose") observe a ratio of #emph[NI] to #emph[TI] of about 0.23. What do we expect this ratio to be? Does this ratio depend on the information content of accounting information?
]

A simple illustrative model is a coin game in which a correct guess wins \$1 and an incorrect guess loses \$1. Independent, equally likely wins and losses let us compare knowing every monthly outcome with knowing only the sign of their annual total. This is an additive, equal-magnitude approximation, not an exact model of compounded stock returns.

If we have 12 coin tosses, the information we can use for #emph[TI] is the outcome of each toss. As such, #emph[TI] should give us \$12. The information we can use for #emph[NI] is whether there are more heads (in which case we would bet "heads" on each toss) or more tails. We can use the #NormalTok("get_ni"); function below to work out the value of #emph[NI] in this coin game.

#Skylighting(([#KeywordTok("def");#NormalTok(" get_ni(n_tosses):");],
[#NormalTok("    n_heads ");#OperatorTok("=");#NormalTok(" np.arange(n_tosses ");#OperatorTok("+");#NormalTok(" ");#DecValTok("1");#NormalTok(")");],
[#NormalTok("    prob ");#OperatorTok("=");#NormalTok(" np.fromiter(");],
[#NormalTok("        (math.comb(n_tosses, ");#BuiltInTok("int");#NormalTok("(x)) ");#ControlFlowTok("for");#NormalTok(" x ");#KeywordTok("in");#NormalTok(" n_heads),");],
[#NormalTok("        dtype");#OperatorTok("=");#BuiltInTok("float");#NormalTok(",");],
[#NormalTok("    )");],
[#NormalTok("    prob ");#OperatorTok("=");#NormalTok(" prob ");#OperatorTok("/");#NormalTok(" prob.");#BuiltInTok("sum");#NormalTok("()");],
[#NormalTok("    value ");#OperatorTok("=");#NormalTok(" n_heads ");#OperatorTok("-");#NormalTok(" (n_tosses ");#OperatorTok("-");#NormalTok(" n_heads)");],
[#NormalTok("    ");#ControlFlowTok("return");#NormalTok(" ");#BuiltInTok("float");#NormalTok("((prob ");#OperatorTok("*");#NormalTok(" np.");#BuiltInTok("abs");#NormalTok("(value)).");#BuiltInTok("sum");#NormalTok("())");],
[],
[#NormalTok("get_ni(");#DecValTok("12");#NormalTok(") ");#OperatorTok("/");#NormalTok(" ");#DecValTok("12");],));
#Skylighting(([#NormalTok("0.2255859375");],));
This is almost exactly the ratio implied by values reported in #cite(<Ball:1968ub>, form: "prose"): $0.2257 approx.eq 0.165 \/ 0.731$. This ratio does not depend on the information content of accounting information. It's not clear that this ratio is relevant to the research questions of #cite(<Ball:2019wu>, form: "prose"). Its agreement with the toy calculation can be interpreted as some evidence consistent with market efficiency under the analogy's assumptions, rather than as a general or uniquely identifying prediction.

#block[
#set enum(numbering: "1.", start: 12)
+ Consider the paragraph in #cite(<Ball:2019wu>, form: "prose", supplement: [p.~418]) beginning "an innovation in BB68 was to estimate …". How do the discussions of these results differ between #cite(<Ball:1968ub>, form: "prose") and #cite(<Ball:2019wu>, form: "prose")?
]

While #cite(<Ball:1968ub>, form: "prose") does talk about portfolios, the main difference seems to be in how the two papers describe the portfolio construction. By 2019, constructing hedge (long-short) portfolios had become a common part of research examining how capital markets process information. But in 1968, the approach used in #cite(<Ball:1968ub>, form: "prose") was novel. In fact, the calculation of the ratio of #emph[II] to #emph[NI] is a rather astounding innovation relative to research at the time (consider the innovative FFJR study, published in 1969).

#block[
#set enum(numbering: "1.", start: 13)
+ Consider column (4) of Table 2 of #cite(<Ball:2019wu>, form: "prose"). Is an equivalent set of numbers reported in BB68? What is the underlying investment strategy associated with this column?
]

Not exactly. We can calculate it for the entire sample period of #cite(<Ball:1968ub>, form: "prose") as $1.060 - 0.914 = 0.146$. This appears to be lower than the value in most years reported in Table 2 of #cite(<Ball:2019wu>, form: "prose").

The underlying investment strategy involves going long in the good news firms and short the bad news firms#footnote[Or equally long and short equal-weighted portfolios of these firms, as implied by the calculated $0.146$ above. It is not entirely clear from the text of #cite(<Ball:2019wu>, form: "prose") what approach was used in Table 2 of that paper.]

BB68's Table 5 reports pooled net-income-model APIs at month $- 1$, rather than a year-by-year column of these portfolio spreads. The $0.146$ calculation illustrates that pooled spread; it is neither a year-specific reproduction of the later paper's Table 2 nor the original BB68 #emph[AI] statistic. A long position in an equal-weighted good-news portfolio and an equally sized short position in a bad-news portfolio compares two group averages. BB68's #emph[AI] calculation additionally weights groups by their numbers of firm-year observations. The strategy also uses future earnings signs before they are available, so this is an informational thought experiment with lookahead, rather than a feasible pre-announcement trading rule. Month $- 1$ is only the closest monthly comparison to the later paper's more precisely defined daily event boundary.

#block[
#set enum(numbering: "1.", start: 14)
+ Heading 6.3 of #cite(<Ball:2019wu>, form: "prose") is "Does 'useful' disprove 'meaningless'?" Do you think that "not meaningless" implies "not useless"? Which questions (or facts) does BB68 address in these terms?
]

I would say that "not meaningless" is a necessary, but not sufficient, condition for "not useless". #cite(<Ball:1968ub>, form: "prose") seem content with a "not meaningless" conclusion, leaving "not useless" to future research (arguably they had done enough for one paper already).

= Replicating #cite(<Ball:1968ub>, form: "prose")
<replicating-ball1968ub>
#figure([
#box(image("bb68-solutions-polars_files/figure-typst/fig-bb-1-output-1.svg", alt: "Cumulative abnormal returns for good versus bad earnings news around annual earnings announcements."))
], caption: figure.caption(
position: bottom, 
[
Replication of Figure 1 of Ball and Brown (1968).
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-bb-1>


== Exercises
<exercises>
+ From the data below, we see that the upper bound for the tenth decile is about US\$544 billion. How can we reconcile this with the existence of firms with market capitalizations over US\$1 trillion? #emph[Bonus:] Using data from #NormalTok("crsp.msf");, identify the firm whose market capitalization was US\$544 billion in December 2020? Why do we need to group by #NormalTok("permco");, not #NormalTok("permno");, to find the answer? (#emph[Hint:] For the bonus question, you can use data from #NormalTok("crsp.msf"); and #NormalTok("crsp.stocknames");. Why do we need to group by #NormalTok("permco");, not #NormalTok("permno");, to find the answer?)

#Skylighting(([#NormalTok("(");],
[#NormalTok("    me_breakpoints_raw");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"month\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" pl.date(");#DecValTok("2020");#NormalTok(", ");#DecValTok("12");#NormalTok(", ");#DecValTok("1");#NormalTok("))");],
[#NormalTok("    .collect()");],
[#NormalTok(")");],));
#table(
  columns: 3,
  align: (auto,auto,auto,),
  table.header([month], [decile], [cutoff],),
  table.hline(),
  [2020-12-01], [1], [327.37],
  [2020-12-01], [2], [772.82],
  [2020-12-01], [3], [1464.26],
  [2020-12-01], [4], [2466.2],
  […], […], […],
  [2020-12-01], [7], [9723.16],
  [2020-12-01], [8], [17140.12],
  [2020-12-01], [9], [37015.1],
  [2020-12-01], [10], [543614.58],
)
#Skylighting(([#NormalTok("co_names ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    stocknames");],
[#NormalTok("    .sort(");#StringTok("\"permco\"");#NormalTok(", ");#StringTok("\"namedt\"");#NormalTok(")");],
[#NormalTok("    .group_by(");#StringTok("\"permco\"");#NormalTok(")");],
[#NormalTok("    .agg(comnam");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"comnam\"");#NormalTok(").last())");],
[#NormalTok(")");],
[],
[#NormalTok("top_stocks ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    msf");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"date\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" pl.date(");#DecValTok("2020");#NormalTok(", ");#DecValTok("12");#NormalTok(", ");#DecValTok("31");#NormalTok("))");],
[#NormalTok("    .with_columns(mktcap");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"prc\"");#NormalTok(").");#BuiltInTok("abs");#NormalTok("() ");#OperatorTok("*");#NormalTok(" pl.col(");#StringTok("\"shrout\"");#NormalTok(") ");#OperatorTok("/");#NormalTok(" ");#DecValTok("1000");#NormalTok(")");],
[#NormalTok("    .join(");],
[#NormalTok("        stocknames");],
[#NormalTok("        .select(");#StringTok("\"permno\"");#NormalTok(", ");#StringTok("\"permco\"");#NormalTok(")");],
[#NormalTok("        .unique(), ");],
[#NormalTok("        on");#OperatorTok("=");#StringTok("\"permno\"");#NormalTok(", how");#OperatorTok("=");#StringTok("\"inner\"");#NormalTok(")");],
[#NormalTok("    .group_by(");#StringTok("\"permco\"");#NormalTok(", ");#StringTok("\"date\"");#NormalTok(")");],
[#NormalTok("    .agg(");],
[#NormalTok("        totmktcap");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"mktcap\"");#NormalTok(").");#BuiltInTok("sum");#NormalTok("(),");],
[#NormalTok("        n_stocks");#OperatorTok("=");#NormalTok("pl.");#BuiltInTok("len");#NormalTok("(),");],
[#NormalTok("    )");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"totmktcap\"");#NormalTok(") ");#OperatorTok(">=");#NormalTok(" math.floor(max_cutoff))");],
[#NormalTok("    .join(co_names, on");#OperatorTok("=");#StringTok("\"permco\"");#NormalTok(", how");#OperatorTok("=");#StringTok("\"inner\"");#NormalTok(")");],
[#NormalTok("    .sort(");#StringTok("\"totmktcap\"");#NormalTok(")");],
[#NormalTok("    .collect()");],
[#NormalTok(")");],
[],
[#NormalTok("top_stocks");],));
#table(
  columns: 5,
  align: (auto,auto,auto,auto,auto,),
  table.header([permco], [date], [totmktcap], [n\_stocks], [comnam],),
  table.hline(),
  [540], [2020-12-31], [543614.57524], [2], [\"BERKSHIRE HATHAWAY INC DEL\"],
  [54084], [2020-12-31], [657222.96], [1], [\"META PLATFORMS INC\"],
  [53453], [2020-12-31], [677340.152983], [1], [\"TESLA INC\"],
  [41593], [2020-12-31], [707732.98458], [13], [\"VANGUARD INDEX FUNDS\"],
  […], […], […], […], […],
  [15473], [2020-12-31], [1.6382e6], [1], [\"AMAZON COM INC\"],
  [8048], [2020-12-31], [1.6784e6], [1], [\"MICROSOFT CORP\"],
  [37493], [2020-12-31], [1.8526e6], [306], [\"ISHARES TRUST\"],
  [7], [2020-12-31], [2.2323e6], [1], [\"APPLE INC\"],
)
This firm is "BERKSHIRE HATHAWAY INC DEL". Note that the cut-offs provided by #link("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_me_breakpoints.html")[Ken French] are for "NYSE stocks that have a CRSP share code of 10 or 11 and have good shares and price data" and "exclude closed end funds and REITs". There are larger stocks, but these are not listed on the NYSE (e.g., Microsoft and Apple are listed on the NASDAQ).

There are two classes of stock for Berkshire Hathaway, so we need to add these to get the total market capitalization. Each class will have its own #NormalTok("permno");, but will share a #NormalTok("permco"); with the other class.

#block[
#set enum(numbering: "1.", start: 2)
+ To keep things straightforward, we focused on firms that have returns for each month in the $\( t - 11 \, t + 6 \)$ window. Can you tell what approach #cite(<Nichols:2004tb>, form: "prose") took with regard to this issue?
]

It is not clear from #cite(<Nichols:2004tb>, form: "prose") exactly what they did. Our restriction makes the plot easier to interpret because every event contributes a complete event-window return path, but it may also discard valid partial histories.

#block[
#set enum(numbering: "1.", start: 3)
+ Table 2 of #cite(<Nichols:2004tb>, form: "prose") measures cumulative abnormal returns as the "cumulative raw return minus cumulative size decile portfolio to which the firm begins." Apart from the use of a size-decile portfolio rather than some other market index, how does this measure differ from the Abnormal Performance Index (API) defined on p.168 of #cite(<Ball:1968ub>, form: "prose")? Adjust the measure depicted in the replication of Figure 1 to more closely reflect the API definition used in #cite(<Ball:1968ub>, form: "prose"). Does this tweak significantly affect the results? Which approach seems most appropriate?
]

#cite(<Ball:1968ub>, form: "prose") instead accumulate monthly abnormal returns. Each approach is feasible (conditional on having a genie supply the income information needed), but implies different strategies for reweighting the market index over time. It seems that #cite(<Ball:1968ub>, form: "prose") will involve more trading to rebalance the market side of the portfolio, so may be more costly to implement in practice.

#block[
#Skylighting(([#NormalTok("alt_plot_data ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    merged");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"ret\"");#NormalTok(").is_not_null())");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        aret_ew");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"ew_ret\"");#NormalTok("),");],
[#NormalTok("        aret_vw");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"vw_ret\"");#NormalTok("),");],
[#NormalTok("    )");],
[#NormalTok("    .sort(");#StringTok("\"gvkey\"");#NormalTok(", ");#StringTok("\"datadate\"");#NormalTok(", ");#StringTok("\"rel_td\"");#NormalTok(")");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        cs.starts_with(");#StringTok("\"aret\"");#NormalTok(").add(");#DecValTok("1");#NormalTok(")");],
[#NormalTok("        .cum_prod().over(");#StringTok("\"gvkey\"");#NormalTok(", ");#StringTok("\"datadate\"");#NormalTok(")");],
[#NormalTok("    )");],
[#NormalTok("    .group_by(");#StringTok("\"rel_td\"");#NormalTok(", ");#StringTok("\"earn_gn\"");#NormalTok(")");],
[#NormalTok("    .agg(cs.starts_with(");#StringTok("\"aret\"");#NormalTok(").mean())");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        pl.when(pl.col(");#StringTok("\"earn_gn\"");#NormalTok("))");],
[#NormalTok("        .then(pl.lit(");#StringTok("\"Good\"");#NormalTok("))");],
[#NormalTok("        .otherwise(pl.lit(");#StringTok("\"Bad\"");#NormalTok("))");],
[#NormalTok("        .alias(");#StringTok("\"Earnings news\"");#NormalTok(")");],
[#NormalTok("    )");],
[#NormalTok("    .collect()");],
[#NormalTok(")");],));
]
As can be seen in #ref(<fig-alt-api>, supplement: [Figure]), making this tweak does not materially change the qualitative pattern in the figure.

#Skylighting(([#NormalTok("(");],
[#NormalTok("    alt_plot_data");],
[#NormalTok("    .ggplot(");],
[#NormalTok("        aes(x");#OperatorTok("=");#StringTok("\"rel_td\"");#NormalTok(", y");#OperatorTok("=");#StringTok("\"aret_ew\"");#NormalTok(",");],
[#NormalTok("            linetype");#OperatorTok("=");#StringTok("\"Earnings news\"");#NormalTok(",");],
[#NormalTok("            group");#OperatorTok("=");#StringTok("\"Earnings news\"");#NormalTok(")");],
[#NormalTok("    )");],
[#NormalTok("    .geom_line()");],
[#NormalTok("    .add_theme(legend_position");#OperatorTok("=");#StringTok("\"bottom\"");#NormalTok(")");],
[#NormalTok(")");],));
#figure([
#box(image("bb68-solutions-polars_files/figure-typst/fig-alt-api-output-1.svg"))
], caption: figure.caption(
position: bottom, 
[
Plot with alternative approach to accumulating returns
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-alt-api>


The baseline difference of buy-and-hold returns is

$ product_m \( 1 + r_(j m) \) - product_m \( 1 + r_(j m)^b \) \, $

whereas a BB68-style API averages firm-level products of monthly abnormal gross returns:

$ A P I_M = 1 / N sum_j product_(m = - 11)^M \( 1 + r_(j m) - r_(j m)^b \) . $

Subtracting one from the API aligns its starting value with an abnormal-return series starting at zero. These quantities generally differ because subtracting a compounded benchmark is not the same as compounding monthly differences. The persistence of good/bad-news separation in the plot is a qualitative comparison, not a statistical test of equality between the methods. For a fixed stock-versus-benchmark buy-and-hold comparison, the first measure has the clearer interpretation. For reproducing BB68's API and its #emph[AI]/#emph[NI] calculations, the monthly-abnormal-return product is the relevant definition. The choice should follow the intended investment or informational comparison.

#block[
#set enum(numbering: "1.", start: 4)
+ Create an alternative version of #ref(<fig-bb-1>, supplement: [Figure]) using the sign of "news" about cash flows in the place of income news. Do your results broadly line up with those in Panel A of Figure 2 of #cite(<Nichols:2004tb>, form: "prose")? Do these results imply that accounting income is inherently more informative than cash flows from operations? Why or why not?
]

The four curves in #ref(<fig-cfo-news>, supplement: [Figure]) broadly follow the ordering in Panel A of Nichols and Wahlen's Figure 2. The larger separation between the income-news portfolios suggests a stronger return association in this sample under these definitions of news. It does not establish that accounting income is inherently more informative than cash flows from operations. Accrual accounting can reduce timing noise in cash receipts and payments, making income a better measure of current performance in some settings. The comparison also depends on the expectations model, firms, periods, and return window. Separate sorts place different firms in the good- and bad-news portfolios; they do not hold the other signal constant. Cash flows may add to information in income, and vice versa. An incremental-information analysis would examine both signals together; these plots alone do not establish a universal ranking or a causal disclosure effect.

Note that I make a small #NormalTok("portfolio_plot_data()"); function that creates a #NormalTok("portfolio"); variable that is a string that can be used to label a plot, as seen in #ref(<fig-cfo-news>, supplement: [Figure]).

#block[
#Skylighting(([#KeywordTok("def");#NormalTok(" portfolio_plot_data(signal):");],
[#NormalTok("    ");#ControlFlowTok("return");#NormalTok(" (");],
[#NormalTok("        plot_data_raw");],
[#NormalTok("        .group_by(");#StringTok("\"rel_td\"");#NormalTok(", signal)");],
[#NormalTok("        .agg(cs.ends_with(");#StringTok("\"ret\"");#NormalTok(").mean())");],
[#NormalTok("        .with_columns(");],
[#NormalTok("            aret_ew");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"ew_ret\"");#NormalTok("),");],
[#NormalTok("            aret_vw");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"vw_ret\"");#NormalTok("),");],
[#NormalTok("            portfolio");#OperatorTok("=");#NormalTok("pl.when(pl.col(signal))");],
[#NormalTok("            .then(pl.lit(signal))");],
[#NormalTok("            .otherwise(pl.lit(signal.replace(");#StringTok("\"_gn\"");#NormalTok(", ");#StringTok("\"_bn\"");#NormalTok("))),");],
[#NormalTok("        )");],
[#NormalTok("        .select(");#StringTok("\"rel_td\"");#NormalTok(", ");#StringTok("\"portfolio\"");#NormalTok(", ");#StringTok("\"aret_ew\"");#NormalTok(", ");#StringTok("\"aret_vw\"");#NormalTok(")");],
[#NormalTok("    )");],
[],
[],
[#NormalTok("plot_data_news ");#OperatorTok("=");#NormalTok(" pl.concat([");],
[#NormalTok("    portfolio_plot_data(");#StringTok("\"cfo_gn\"");#NormalTok("),");],
[#NormalTok("    portfolio_plot_data(");#StringTok("\"earn_gn\"");#NormalTok("),");],
[#NormalTok("]).collect()");],));
]
#Skylighting(([#NormalTok("(");],
[#NormalTok("    plot_data_news");],
[#NormalTok("    .ggplot(");],
[#NormalTok("        aes(x");#OperatorTok("=");#StringTok("\"rel_td\"");#NormalTok(", y");#OperatorTok("=");#StringTok("\"aret_ew\"");#NormalTok(", color");#OperatorTok("=");#StringTok("\"portfolio\"");#NormalTok(")");],
[#NormalTok("    )");],
[#NormalTok("    .geom_line()");],
[#NormalTok("    .add_theme(legend_position");#OperatorTok("=");#StringTok("\"bottom\"");#NormalTok(")");],
[#NormalTok(")");],));
#figure([
#box(image("bb68-solutions-polars_files/figure-typst/fig-cfo-news-output-1.svg"))
], caption: figure.caption(
position: bottom, 
[
Abnormal performance index by sign of cash flow and earnings news
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-cfo-news>


#block[
#set enum(numbering: "1.", start: 5)
+ Create an alternative version of the figure above focused on the extreme earnings deciles in place of the good-bad news dichotomy. Do your results broadly line up with those in Panel B of Figure 2 of #cite(<Nichols:2004tb>, form: "prose")?
]

In the code below, I use #NormalTok("pl.concat()"); to stack two data frames---one for extreme deciles of earnings news and one for extreme deciles of cash-flow news---to create #NormalTok("plot_data_extreme");.

#block[
#Skylighting(([#NormalTok("plot_data_extreme ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    pl.concat([");],
[#NormalTok("        (");],
[#NormalTok("            plot_data_raw");],
[#NormalTok("            .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"earn_decile\"");#NormalTok(").is_in([");#DecValTok("1");#NormalTok(", ");#DecValTok("10");#NormalTok("]))");],
[#NormalTok("            .group_by(");#StringTok("\"rel_td\"");#NormalTok(", ");#StringTok("\"earn_decile\"");#NormalTok(")");],
[#NormalTok("            .agg(cs.ends_with(");#StringTok("\"ret\"");#NormalTok(").mean())");],
[#NormalTok("            .with_columns(");],
[#NormalTok("                aret_ew");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"ew_ret\"");#NormalTok("),");],
[#NormalTok("                aret_vw");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"vw_ret\"");#NormalTok("),");],
[#NormalTok("                portfolio");#OperatorTok("=");#NormalTok("pl.when(pl.col(");#StringTok("\"earn_decile\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" ");#DecValTok("10");#NormalTok(")");],
[#NormalTok("                .then(pl.lit(");#StringTok("\"earn_decile_10\"");#NormalTok("))");],
[#NormalTok("                .otherwise(pl.lit(");#StringTok("\"earn_decile_1\"");#NormalTok(")),");],
[#NormalTok("            )");],
[#NormalTok("            .select(");#StringTok("\"rel_td\"");#NormalTok(", ");#StringTok("\"portfolio\"");#NormalTok(", ");#StringTok("\"aret_ew\"");#NormalTok(", ");#StringTok("\"aret_vw\"");#NormalTok(")");],
[#NormalTok("        ),");],
[#NormalTok("        (");],
[#NormalTok("            plot_data_raw");],
[#NormalTok("            .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"cfo_decile\"");#NormalTok(").is_in([");#DecValTok("1");#NormalTok(", ");#DecValTok("10");#NormalTok("]))");],
[#NormalTok("            .group_by(");#StringTok("\"rel_td\"");#NormalTok(", ");#StringTok("\"cfo_decile\"");#NormalTok(")");],
[#NormalTok("            .agg(cs.ends_with(");#StringTok("\"ret\"");#NormalTok(").mean())");],
[#NormalTok("            .with_columns(");],
[#NormalTok("                aret_ew");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"ew_ret\"");#NormalTok("),");],
[#NormalTok("                aret_vw");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"vw_ret\"");#NormalTok("),");],
[#NormalTok("                portfolio");#OperatorTok("=");#NormalTok("pl.when(pl.col(");#StringTok("\"cfo_decile\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" ");#DecValTok("10");#NormalTok(")");],
[#NormalTok("                .then(pl.lit(");#StringTok("\"cfo_decile_10\"");#NormalTok("))");],
[#NormalTok("                .otherwise(pl.lit(");#StringTok("\"cfo_decile_1\"");#NormalTok(")),");],
[#NormalTok("            )");],
[#NormalTok("            .select(");#StringTok("\"rel_td\"");#NormalTok(", ");#StringTok("\"portfolio\"");#NormalTok(", ");#StringTok("\"aret_ew\"");#NormalTok(", ");#StringTok("\"aret_vw\"");#NormalTok(")");],
[#NormalTok("        ),");],
[#NormalTok("    ])");],
[#NormalTok("    .collect()");],
[#NormalTok(")");],));
]
It is then easy to plot the data in #NormalTok("plot_data_extreme"); to create #ref(<fig-ext-decs>, supplement: [Figure]).

#Skylighting(([#NormalTok("(");],
[#NormalTok("    plot_data_extreme");],
[#NormalTok("    .ggplot(aes(x");#OperatorTok("=");#StringTok("\"rel_td\"");#NormalTok(", y");#OperatorTok("=");#StringTok("\"aret_ew\"");#NormalTok(", color");#OperatorTok("=");#StringTok("\"portfolio\"");#NormalTok("))");],
[#NormalTok("    .geom_line()");],
[#NormalTok("    .add_theme(legend_position");#OperatorTok("=");#StringTok("\"bottom\"");#NormalTok(")");],
[#NormalTok(")");],));
#figure([
#box(image("bb68-solutions-polars_files/figure-typst/fig-ext-decs-output-1.svg"))
], caption: figure.caption(
position: bottom, 
[
Plot with extreme deciles
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-ext-decs>


The results broadly line up with Panel B of Figure 2 in #cite(<Nichols:2004tb>, form: "prose"). Using extreme deciles produces a cleaner spread than simply splitting at zero, which is what we would expect if the magnitude of the earnings or cash-flow surprise matters.

#block[
#set enum(numbering: "1.", start: 6)
+ Calculate #emph[AI] by year following the formula on p.~175 of #cite(<Ball:1968ub>, form: "prose") (there denoted as $I I_0$).
]

#Skylighting(([#NormalTok("api_returns ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    merged");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"ret\"");#NormalTok(").is_not_null())");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        api_ew");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"ew_ret\"");#NormalTok("),");],
[#NormalTok("        api_vw");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ret\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" pl.col(");#StringTok("\"vw_ret\"");#NormalTok("),");],
[#NormalTok("    )");],
[#NormalTok("    .sort(");#StringTok("\"gvkey\"");#NormalTok(", ");#StringTok("\"datadate\"");#NormalTok(", ");#StringTok("\"rel_td\"");#NormalTok(")");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        pl.col(");#StringTok("\"api_ew\"");#NormalTok(", ");#StringTok("\"api_vw\"");#NormalTok(").add(");#DecValTok("1");#NormalTok(")");],
[#NormalTok("        .cum_prod().over(");#StringTok("\"gvkey\"");#NormalTok(", ");#StringTok("\"datadate\"");#NormalTok(").sub(");#DecValTok("1");#NormalTok(")");],
[#NormalTok("    )");],
[#NormalTok("    .");#BuiltInTok("filter");#NormalTok("(pl.col(");#StringTok("\"rel_td\"");#NormalTok(") ");#OperatorTok("==");#NormalTok(" ");#DecValTok("0");#NormalTok(")");],
[#NormalTok("    .select(");#StringTok("\"gvkey\"");#NormalTok(", ");#StringTok("\"datadate\"");#NormalTok(", ");#StringTok("\"year\"");#NormalTok(", ");#StringTok("\"earn_gn\"");#NormalTok(", ");#StringTok("\"api_ew\"");#NormalTok(", ");#StringTok("\"api_vw\"");#NormalTok(")");],
[#NormalTok("    .collect()");],
[#NormalTok(")");],
[],
[#NormalTok("ai_data ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    api_returns");],
[#NormalTok("    .with_columns(news_sign");#OperatorTok("=");#NormalTok("pl.when(pl.col(");#StringTok("\"earn_gn\"");#NormalTok(")).then(");#DecValTok("1");#NormalTok(").otherwise(");#OperatorTok("-");#DecValTok("1");#NormalTok("))");],
[#NormalTok("    .group_by(");#StringTok("\"year\"");#NormalTok(")");],
[#NormalTok("    .agg(");],
[#NormalTok("        ai_ew");#OperatorTok("=");#NormalTok("(pl.col(");#StringTok("\"news_sign\"");#NormalTok(") ");#OperatorTok("*");#NormalTok(" pl.col(");#StringTok("\"api_ew\"");#NormalTok(")).mean(),");],
[#NormalTok("        ai_vw");#OperatorTok("=");#NormalTok("(pl.col(");#StringTok("\"news_sign\"");#NormalTok(") ");#OperatorTok("*");#NormalTok(" pl.col(");#StringTok("\"api_vw\"");#NormalTok(")).mean(),");],
[#NormalTok("    )");],
[#NormalTok("    .sort(");#StringTok("\"year\"");#NormalTok(")");],
[#NormalTok(")");],
[#NormalTok("ai_data");],));
#table(
  columns: 3,
  align: (auto,auto,auto,),
  table.header([year], [ai\_ew], [ai\_vw],),
  table.hline(),
  [1988], [0.115339], [0.116284],
  [1989], [0.166923], [0.164199],
  [1990], [0.198726], [0.203671],
  [1991], [0.163895], [0.185409],
  […], […], […],
  [1999], [0.098588], [0.082749],
  [2000], [0.214325], [0.241051],
  [2001], [0.183881], [0.18344],
  [2002], [0.107628], [0.104399],
)
AI weights every firm equally; it is not an equal-weighted average of two news-group means when their counts differ. The stock-level API increments use the assigned compounded-monthly-abnormal-return definition.

#block[
#set enum(numbering: "1.", start: 7)
+ Calculate #emph[NI] by year following the formula on p.~175 of #cite(<Ball:1968ub>, form: "prose") (there denoted as $N I_0$).
]

#Skylighting(([#NormalTok("ni_data ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    api_returns");],
[#NormalTok("    .group_by(");#StringTok("\"year\"");#NormalTok(")");],
[#NormalTok("    .agg(");],
[#NormalTok("        ni_ew");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"api_ew\"");#NormalTok(").");#BuiltInTok("abs");#NormalTok("().mean(),");],
[#NormalTok("        ni_vw");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"api_vw\"");#NormalTok(").");#BuiltInTok("abs");#NormalTok("().mean(),");],
[#NormalTok("    )");],
[#NormalTok("    .sort(");#StringTok("\"year\"");#NormalTok(")");],
[#NormalTok(")");],
[#NormalTok("ni_data");],));
#table(
  columns: 3,
  align: (auto,auto,auto,),
  table.header([year], [ni\_ew], [ni\_vw],),
  table.hline(),
  [1988], [0.255044], [0.254519],
  [1989], [0.303139], [0.301249],
  [1990], [0.360228], [0.363337],
  [1991], [0.361835], [0.372625],
  […], […], […],
  [1999], [0.723941], [0.720743],
  [2000], [0.463129], [0.50265],
  [2001], [0.415014], [0.412924],
  [2002], [0.376163], [0.37465],
)
#block[
#set enum(numbering: "1.", start: 8)
+ Using the data on #emph[NI] and #emph[AI] from above, create a plot of $A I \/ N I$ like that in Figure 2 of #cite(<Ball:2019wu>, form: "prose"). Do you observe similar results to those shown in Figure 2 of #cite(<Ball:2019wu>, form: "prose")?
]

Credit for this question goes to Philip Brown. I start by joining the #emph[NI] and #emph[AI] data calculated in the responses to the previous questions. I then calculate both value-weighted and equal-weighted versions of the ratios, then #NormalTok(".unpivot()"); the data so that it is easier to plot both series on one plot.

#block[
#Skylighting(([#NormalTok("ai_ni_data ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    ni_data");],
[#NormalTok("    .join(ai_data, on");#OperatorTok("=");#StringTok("\"year\"");#NormalTok(", how");#OperatorTok("=");#StringTok("\"inner\"");#NormalTok(")");],
[#NormalTok("    .with_columns(");],
[#NormalTok("        ai_to_ni_ew");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ai_ew\"");#NormalTok(") ");#OperatorTok("/");#NormalTok(" pl.col(");#StringTok("\"ni_ew\"");#NormalTok("),");],
[#NormalTok("        ai_to_ni_vw");#OperatorTok("=");#NormalTok("pl.col(");#StringTok("\"ai_vw\"");#NormalTok(") ");#OperatorTok("/");#NormalTok(" pl.col(");#StringTok("\"ni_vw\"");#NormalTok("),");],
[#NormalTok("    )");],
[#NormalTok("    .unpivot(");],
[#NormalTok("        on");#OperatorTok("=");#NormalTok("[");#StringTok("\"ai_to_ni_ew\"");#NormalTok(", ");#StringTok("\"ai_to_ni_vw\"");#NormalTok("],");],
[#NormalTok("        index");#OperatorTok("=");#StringTok("\"year\"");#NormalTok(",");],
[#NormalTok("        variable_name");#OperatorTok("=");#StringTok("\"measure\"");#NormalTok(",");],
[#NormalTok("        value_name");#OperatorTok("=");#StringTok("\"value\"");#NormalTok(",");],
[#NormalTok("    )");],
[#NormalTok(")");],));
]
In #ref(<fig-ai-ni>, supplement: [Figure]), we see similar results to those in Figure 2 of #cite(<Ball:2019wu>, form: "prose"), but not exactly the same numbers in each year. For example, we have less volatility in the ratio in our data and 1999 (the peak of the "dot-com boom") is more clearly an outlier in our data.

#Skylighting(([#NormalTok("(");],
[#NormalTok("    ai_ni_data");],
[#NormalTok("    .ggplot(aes(x");#OperatorTok("=");#StringTok("\"year\"");#NormalTok(", y");#OperatorTok("=");#StringTok("\"value\"");#NormalTok(", color");#OperatorTok("=");#StringTok("\"measure\"");#NormalTok("))");],
[#NormalTok("    .geom_point()");],
[#NormalTok("    .geom_line()");],
[#NormalTok("    .add_theme(legend_position");#OperatorTok("=");#StringTok("\"bottom\"");#NormalTok(")");],
[#NormalTok(")");],));
#figure([
#box(image("bb68-solutions-polars_files/figure-typst/fig-ai-ni-output-1.svg"))
], caption: figure.caption(
position: bottom, 
[
AI-to-NI plot
]), 
kind: "quarto-float-fig", 
supplement: "Figure", 
)
<fig-ai-ni>


#pagebreak(weak: true)
= References
<references>
#block[
] <refs>



#set bibliography(style: "linkedin-solutions.csl")

#bibliography(("linkedin-solutions-references.bib"))

