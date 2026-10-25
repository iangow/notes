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
  title: [Trump's tariff formula],
  authors: (
    ( name: [Ian D. Gow],
      affiliation: [],
      email: [] ),
    ),
  date: [7 April 2025],
  font: ("Libertinus Serif",),
  heading-family: ("Libertinus Serif",),
  mathfont: ("New Computer Modern Math",),
  linkcolor: [\#0000FF],
  toc_title: [Table of contents],
  toc_depth: 3,
  doc,
)

#emph[This note combines my #link("https://www.linkedin.com/posts/iangow_trumps-tariff-formula-activity-7315012826006196225-gQX2")[LinkedIn post of 7 April 2025] with its #link("https://iangow.github.io/notes/tariffs.pdf")[attached PDF], with light editing and clarifications. It discusses the tariff announcement of April 2025 and retains the historical figures used then.]

As it's not often that a mathematical formula with Greek letters gets so much attention, lovers of equations might be excited(?) about the publicity for Trump's tariff formula … though they might be less thrilled about the impact on their stock portfolios, etc. The formula is:

$ Delta tau_i = frac(x_i - m_i, epsilon.alt thin phi thin m_i) . $

While one explanation was provided by President Trump "himself" on #link("https://youtu.be/VEle3pZRqmI?t=192")[Saturday Night Live], in this note I will offer a slightly different one. First, $x_i$ represents US exports of goods to country $i$, and $m_i$ means US imports of goods from that country.

= The elasticity term
<the-elasticity-term>
What is $epsilon.alt$? If you know any economics (and even if you don't), you probably understand that increases in the price of a good generally lead to less demand for that good. But how much less? This is where $epsilon.alt$ comes in. It represents the price elasticity of demand for imports, where $q$ is quantity demanded, $p$ is price, and $Delta$ represents the change in the indicated quantity:

$ epsilon.alt = frac(Delta q, q) div frac(Delta p, p) . $

In other words, $epsilon.alt$ indicates the estimated percentage change in quantity ($Delta q \/ q$) for a given percentage change in price ($Delta p \/ p$).#footnote[Strictly speaking, "percentages" mean multiplying by 100, but this happens in both the numerator and the denominator, thus cancelling out.] With this sign convention, a fall in demand as prices rise means $epsilon.alt < 0$.

If the goal of trade policy is to eliminate goods trade deficits, the required proportional change in imports is approximated by $\( x_i - m_i \) \/ m_i$, holding exports fixed and valuing imports at their initial prices.#footnote[Much has been written on the folly (e.g., #link("https://www.brookings.edu/articles/the-us-trade-deficit-myths-and-realities/")[by Maurice Obstfeld]) of having this as a goal of trade policy, so I see little chance that I can add much to that here.] So, using this approximation, we have:

$ epsilon.alt = frac(x_i - m_i, m_i) div frac(Delta p, p) . $

#pagebreak()
= From tariffs to prices
<from-tariffs-to-prices>
Now we just need to figure out $Delta p \/ p$. This is where tariffs come in. If the existing tariff is zero and we impose a tariff of $tau_i$, then the change in the tariff rate is $Delta tau_i = tau_i$. But perhaps the full amount of the tariff will not be passed along as a price increase. This is where $phi$, the assumed passthrough rate, comes in. Given an increase in tariff rates of $Delta tau_i$ and passthrough rate of $phi$, the proportional increase in prices will be $Delta tau_i thin phi$:

$ epsilon.alt = frac(x_i - m_i, m_i) div (Delta tau_i thin phi) . $

Moving $Delta tau_i$ to the left and $epsilon.alt$ to the right, we have the now-famous formula:

$ Delta tau_i = frac(x_i - m_i, epsilon.alt thin phi thin m_i) . $

The #link("https://ustr.gov/sites/default/files/files/Issue_Areas/Presidential%20Tariff%20Action/Reciprocal%20Tariff%20Calculations.pdf")[USTR explanation] selects an import-demand elasticity with magnitude 4 and a passthrough rate of $phi = 0.25$. In the signed notation above, that elasticity is $epsilon.alt = - 4$. The formula then reduces to the goods trade deficit divided by imports:

$ Delta tau_i = frac(m_i - x_i, m_i) . $

This is the calculated rate for eliminating the deficit in the simplified model. The announced rates were "generous" in that they were roughly half the calculated balancing rates, with a 10% baseline for other countries.#footnote[The #link("https://www.whitehouse.gov/fact-sheets/2025/04/fact-sheet-president-donald-j-trump-declares-national-emergency-to-increase-our-competitive-edge-protect-our-sovereignty-and-strengthen-our-national-and-economic-security/")[April 2 announcement] describes the 10% baseline and higher country-specific rates, with product and country exceptions. Apart from ignoring existing US tariffs, the USTR calculation assumes away offsetting exchange-rate effects, general-equilibrium effects, and retaliation.]

= What the formula assumes
<what-the-formula-assumes>
The whole premise of the formula is that tariffs are, in part, passed along as increases in the prices of imports … so much for the idea that the suppliers of the imports would necessarily wear all the effects of the tariffs! Without price increases, the formula's demand channel implies there would be no change in imports, hence no narrowing of the trade deficit in goods.

With the 2024 #link("https://ustr.gov/countries-regions/china-mongolia-taiwan/peoples-republic-china")[imports of \$438.9 billion] used in my original note and the #link("https://www.whitehouse.gov/wp-content/uploads/2025/04/Annex-I.pdf")[announced tariff rate of 34%], a fixed-quantity calculation puts the increase in the import bill from China at about \$37 billion under the assumed passthrough rate:

$ \$ 438.9 upright(" billion") times 0.34 times 0.25 approx \$ 37 upright(" billion") . $

However, researchers quoted by #link("https://www.ft.com/content/bbaa8daf-b7b0-4dca-bc23-c2e8eee6835d")[FT Alphaville] argued that $phi = 0.25$ was too low and a better estimate would be "very close to 1". With $phi = 1$, the increase on this fixed-quantity basis would be close to \$150 billion. For the #link("https://ustr.gov/countries-regions/europe-middle-east/europe/european-union")[European Union], the corresponding illustration in the original note exceeded \$120 billion.#footnote[These illustrations use the 2024 trade figures quoted in April 2025; the live country pages now show later data. Here I also get to set aside general-equilibrium effects! They hold import quantities fixed to illustrate the price change, rather than estimating the final import bill or the net economic cost after trade adjusts.]

To paraphrase one-time US senator #link("https://web.archive.org/web/20040816153245/http://www.dirksencenter.org/print_emd_billionhere.htm")[Everett Dirksen], "a \[few hundred\] billion here, a \[few hundred\] billion there, and pretty soon you're talking real money."

The #link("https://iangow.github.io/notes/published/tariffs.typ")[Typst source] for this version is also available.
