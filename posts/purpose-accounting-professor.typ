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
  title: [The purpose of an accounting professor?],
  authors: (
    ( name: [Ian D. Gow],
      affiliation: [],
      email: [] ),
    ),
  date: [2 February 2022],
  font: ("Libertinus Serif",),
  fontsize: 10.5pt,
  heading-family: ("Libertinus Serif",),
  mathfont: ("New Computer Modern Math",),
  linkcolor: [\#0000FF],
  toc_title: [Table of contents],
  toc_depth: 3,
  doc,
)

#emph[Originally published on #link("https://www.linkedin.com/pulse/purpose-accounting-professor-ian-gow/")[LinkedIn] on 2022-02-02 (UTC).]

Recently, Professor Alex Edmans of London Business School posted a paper entitled “#link("https://doi.org/10.1111/fima.12387")[The Purpose of a Finance Professor]” based on a speech he gave in 2021. Edmans argues that “the academic finance profession has the potential to be uniquely purposeful due to four characteristics --- the freedom to take risks and work on what we're passionate about, the loyalty to our profession rather than institution, the collaborative nature of the creation and dissemination of knowledge, and the magnitude of our potential impact.”

Edmans's piece is presumably of relevance to academic accounting because finance is such a closely related discipline. Some of what you see the top accounting journals was probably considered by one or more finance journals before “finding a home” in a “more appropriate outlet” in accounting. Some of the remainder is essentially finance research that is deemed accounting research because of a focus on variables, such as voluntary disclosure or earnings management, that are not of much interest to finance researchers or simply because the authors identify as accounting researchers.

But do these four characteristics apply to accounting academia?

While Edmans does not say so explicitly, his piece overwhelmingly emphasizes the research side of being a professor rather than teaching and I retain that emphasis here.

On “the freedom to take risks and work on what we're passionate about,” there seems to be increasing recognition that much of accounting research is the result of #link("https://www.linkedin.com/pulse/p-hacking-accounting-research-ian-gow")[p-hacking] (actually #link("https://www.ft.com/content/9025393f-76da-4b8f-9436-4341485c75d0")[some say] this is true in finance). Given that p-hacking is the somewhat mindless search for spurious correlations that can be passed off as the predictions of some so-called theory, one would have to be psychopathic to be “passionate about” that type of research. So what gives? Well, the reality is that one has the “freedom” to work on whatever will be accepted by journals. “Statistically significant” results from studying a purported effect of some “exogenous shock” on an accounting variable like earnings management? Check. Null results from a multi-year deep-dive into something of real interest? “Best of luck finding a home in a more appropriate outlet.”

The overwhelming majority of accounting academics are at institutions where the only really important performance metric is the number of papers published in certain “top” journals and where academics risk being out of a job (or suffering other adverse consequences) if they don't perform. Evidence that “work\[ing\] on what we're passionate about” is a luxury enjoyed by few comes from the papers that fill up most journals that seem deathly dull before you get past the title. I have no doubt that there are brilliant people in accounting working on passion projects and getting published, but I think it's a small minority much envied by the rest of us.

What Edmans means by “loyalty to our profession, rather than institution” is not entirely clear, but it does describe a rather interesting feature of academia that surely applies as much in accounting as it does in finance and that is probably better described as “institutional irrelevance” or something like that. I worked in finance for General Motors until the very last day of 2003. That was a very busy period, as 31 December was a real (tax) deadline and we were working on several projects to create value for GM. But at the end of that last day, I shut down and handed in my computer, closed my file drawers, and never worked a second on those projects again. In contrast, an academic might be working on research projects X, Y, and Z on 30 June at University A, then start at University B on 1 July, where she … continues on projects X, Y, and Z. This institutional irrelevance #emph[is ]an odd characteristic of some parts of academia, including accounting. But I don't see it as a source of “purpose” in any real way and don't count it as such. (One consequence is that one often has no meaningful professional connection with one's #emph[institutional] colleagues.)

Turning to the next characteristic, a big part of “the collaborative nature of the creation and dissemination of knowledge” in the mind of Edmans appears to be the supposed “non-rivalry” of academia. Here a hypothetical example seems helpful. Suppose some index of ESG-ness emerged that gave a continuous ESG score to firms based on their performance on matters environmental, social, and governance, then divided the firms into “ESG good guys” and the rest based on some arbitrary score cutoff. There would be a #link("https://iangow.github.io/far_book/rdd.html")[discontinuity-enabled] research feast to be had. Perhaps the smarter and better-resourced researchers would bite into the meatier topics, but accounting researchers would get to nibble on the effects being deemed an “ESG good guy” on earnings management and such like. But even here there would be rivalry. Journals #emph[might] tolerate #link("https://iangow.github.io/far_book/rdd.html#russell-10002000-and-stuff-mostly-taxes")[two or three contemporaneous papers] on a given topic, but if you're late, you're out of luck. And being late might be a function of getting unlucky at the first journal rather than being late to execute the idea (e.g., taking a punt at a finance journal, but getting rejected and “scooped” by a paper that went #link("https://en.wikipedia.org/wiki/Direct-to-video")[direct-to-accounting]).

Rivalry is perceived to be so bad that many researchers I know are reluctant to reveal any hints of their research ideas, let alone post manuscripts on SSRN, until their papers have been accepted at a journal, lest their “ideas” be taken by better-connected researchers. So I'm not sure about this “non-rivalry” thing in accounting. I'm not even convinced it applies in finance. Top journals pride themselves on the fact that they reject the overwhelming majority of submissions because the rivalrous nature of their limited publication capacity is a critical element of the signal that publication conveys.

On the last point (“potential impact”), Edmans says “our research can be read by thousands of people.” But that is arguably understating it in a world in which billions of people have access to the internet and most papers can be made available for free. Instead, it should read “our research can be read by #emph[billions] of people.” The question is whether people #emph[do] read them. If I'm a harried researcher trying to publish enough papers to keep my job (and empirically many are), then even for an accounting academic, reading papers seems like a poor use of time. That time could be spent scanning top economics and finance journals for “exogenous shocks” or, having found such shocks, scanning the internet to make sure no-one has done the “effect of \[shock\] on earnings management” paper already.

According to a #link("https://arxiv.org/pdf/physics/0701012")[2007 study] cited in a #link("https://www.smithsonianmag.com/smart-news/half-academic-studies-are-never-read-more-three-people-180950222/")[Smithsonian Magazine article] “half of academic papers are read only by their authors and journal editors” (confession: I didn't read the 2007 study … I didn't even click the link). The study leveraged the reality that citing a paper does not mean you've read it … or even obtained it. The cited claim seems a little off-base in accounting research, as we'd expect it to be the reviewers reading papers more than the editors. Yet we've all had those reviews where it's obvious that the reviewer hasn't read the paper. I can think of some recent seminars where it seems that the (typically senior) presenting co-author hasn't read the paper, an impression reinforced by those papers with native-English-speaker co-authors that read as though they've been run through Google Translate. So maybe billions is a merely #emph[theoretical] maximum. (I've written #link("https://www.linkedin.com/pulse/do-we-need-accounting-research-ian-gow/")[elsewhere] about my scepticism about the merits of those billions adding accounting research to their reading lists, especially in world where “#link("https://www.smithsonianmag.com/smart-news/half-academic-studies-are-never-read-more-three-people-180950222/")[1.8 million \[scientific\] articles \[are\] published each year, in about 28,000 journals.]”)

In summary, whatever the purpose of an accounting professor is, it's hard to see that it comes from the four characteristics identified by Edmans for finance professors. Three seem not to apply to accounting research in general and the fourth seems to describe a quirk of academia rather than a source of purpose. Perhaps an enthusiastic accounting academic (evidently not I!) needs to write the equivalent of Edmans's piece for accounting research.
