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
  margin: (x: 2.5cm,y: 2.5cm,),
  numbering: "1",
  columns: 1,
)

#show: doc => article(
  title: [Valuation methods],
  subtitle: [Draft for review],
  authors: (
    ( name: [Ian D. Gow],
      affiliation: [],
      email: [] ),
    ),
  date: [30 April 2025],
  font: ("Libertinus Serif",),
  heading-family: ("Libertinus Serif",),
  mathfont: ("New Computer Modern Math",),
  linkcolor: [\#0000FF],
  toc_title: [Table of contents],
  toc_depth: 3,
  doc,
)

#block[
#callout(
body:
[
The final section, "Cash flow versus economic profit", is incomplete. The text below otherwise reproduces the original draft.

]
,
title:
[
Unfinished draft
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
Chapter 10 of #cite(<Koller:2020aa>, form: "prose")---"Frameworks for Valuation"---provides a helpful taxonomy of approaches to valuation of companies. There are three key dimensions on which the models considered in #cite(<Koller:2020aa>, form: "prose") differ.

- Cash flow versus economic profit
- Entity versus proprietary measures of cash flow
- Approach to tax benefits of debt.

For the last item, #cite(<Koller:2020aa>, form: "prose") discusses three approaches. The first approach ("WACC") incorporates the tax benefits of debt in the weighted average cost of capital. The second approach is known as adjusted present value ("APV") and essentially treats the tax benefit of debt as a separate set of cash flows to be valued and added to the value of the underlying business. The third approach (CCF) calculates periodic cash flows as the sum of free cash flows and interest tax shields. Given certain assumptions, CCF will yield identical results to the other two, so #cite(<Koller:2020aa>, form: "prose") recommends those other approaches. These assumptions also lead to equivalence of WACC and APV. Given the complexity introduced by deviation from these assumptions would take me too far astray of my goal here, I ignore this dimension of the taxonomy and focus on the other two dimensions.

= Entity versus proprietary measures of cash flow
<entity-versus-proprietary-measures-of-cash-flow>
#cite(<Koller:2020aa>, form: "prose") do not use the "entity" and "proprietary" terminology, but enterprise discounted cash flow uses the entity approach (i.e., valuing the whole enterprise or entity first) and the equity cash flow model applies the proprietary approach. While the terms "entity" and "proprietary" have their heritage in a stream of accounting thought unfamiliar to modern accounting academics, they seem useful nonetheless.

In the context of valuation, the proprietary approach is perhaps easiest to explain. The proprietary approach requires forecasting cash flows to holders of the residual equity claim and then discounting these at an appropriate rate to calculate a value of that equity claim. Simple! The phrase "an appropriate rate" is doing a lot of heavy lifting here. Standard finance theory would suggest that, even with assets with fixed risk attributes, the appropriate discount rate will be a function of leverage and the timing of the cash flows.

A core idea of finance is that it is the risk attributes of assets that drive expected returns rather than how those assets are financed. Practitioners will often make claims such as "entity $X$ has a lower cost of capital than other entities so it can afford to discount operating asset $Z$ at a lower rate."#footnote[Here I assume that there are no operating synergies between the asset $Z$ and other assets of entity $X$. I will explain the term "operating" in a moment.] One corollary of such a claim is that $X$ will value asset $Z$ more than other entities. Such claims are often predicated on the idea that assets can be financed with debt (e.g., "Entity X can borrow at $y %$, so we should discount cash flows at $y %$").

Such claims are #emph[not] endorsed by standard finance theory. While the classic reference is #cite(<Modigliani:1958aa>, form: "prose"), an extensive literature has refined the Modigliani-Miller framework and #cite(<Koller:2020aa>, form: "prose") provides excellent discussion of the topic. #cite(<Modigliani:1958aa>, form: "prose") speaks of the concept of "a firm" and generally equates a firm as comprising "physical assets" financed by equity and debt. However, reality can be more complex.

First, a firm might comprise shares in other firms and interests in partnerships and joint ventures. Accountants have grappled with the practical issues related to defining "a firm" for many decades resulting in standards such as IFRS 10, which requires the presentation of #strong[consolidated financial statements] for a #strong[group], which can be considered as practical notion of the firm in real-world economic situations. For the purposes of this note, I will shelve the complexities here and assume that we have a simple single-company business.

Second, few (if any) businesses today can be viewed as the operation of physical assets financed by debt and equity. Physical assets are only a fraction of the reported balance sheets of most firms today, with financial and intangible assets being increasingly important.#footnote[Additionally, it is widely recognized that many intangible assets are either undervalued or completely missing from reported balance sheets due to limitations of the governing accounting standards.] Often financial assets will be managed as part of the financial strategy of the firm and thus, for reasons to be discussed shortly, are best considered in conjunction with debt rather than being valued with other assets of the business.

Similarly, the claims on a firm's assets will not be limited to debt and equity. Firms will have obligations to customers, employees, and suppliers arising out of the ordinary course of business and it is generally inappropriate to value these in the same way one might value claims such as debt and equity. Also, firms will often have obligations (i.e., liabilities) that are best thought of as debt-like claims on the business.#footnote[Another issue is that firms may have liabilities that are missing from the balance sheet. Fortunately accounting standards are generally #strong[conservative] and this means that they are much less inclined to permit unreported or understated liabilities than is the case with assets. In the past, firms obligations for pensions and other post-retirement benefits and leases were understated, but accounting standards have generally moved to close such gaps over time.]

Putting aside issues of missing or misvalued assets and liabilities, we can repurpose the balance sheet equation for valuation purposes. This has assets equal to liabilities and shareholders' equity:

$ A = L + S E $

It is important to note that this relation is an #strong[accounting identity] not simply a model that might be approximately true. We can break down the assets and liabilities into operating and financing resulting in the following:

$ O A + F A = O L + F L + S E $ where $O A$ and $F A$ are operating and financing assets, respectively, and $O L$ and $F L$ are operating and financing liabilties, respectively.

We can rearrange terms to get

$ O A - O L = \( F L - F A \) + S E $ A standard building block in the entity approach as discussed in #cite(<Koller:2020aa>, form: "prose") is #strong[free cash flow], which is defined as the "the after-tax cash flow that would be generated if the company … financed the business entirely with equity" @Koller:2020aa[p.~209]. With all-equity financing and denoting #strong[net operating assets] as $italic("NOA")$, we have:

$ italic("NOA") = O A - O L = S E $ The #strong[clean surplus assumption] requires that changes in $S E$ relate with to net income ($N I$) or dividends $D$:

$ Delta S E = N I - D $

But $Delta S E = Delta italic("NOA")$, so

$ D = N I - Delta italic("NOA") $ Because there are no financial assets or liabilities, net income is the same as #strong[net operating profit after tax] or NOPAT.

$ D = italic("NOPAT") - Delta italic("NOA") $

= Cash flow versus economic profit
<cash-flow-versus-economic-profit>
While #cite(<Koller:2020aa>, form: "prose") only considers economic profit in conjunction with one variant of the

#block[
] <refs>



#set bibliography(style: "harvard-cite-them-right")

#bibliography(("../papers.bib"))
