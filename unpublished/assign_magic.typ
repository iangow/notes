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
#show block.where(fill: rgb("#f1f3f5")): set block(breakable: false)
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
  title: [Explaining some #NormalTok(".assign()"); idioms],
  subtitle: [Draft for review],
  authors: (
    ( name: [Ian D. Gow],
      affiliation: [],
      email: [] ),
    ),
  date: [7 February 2026],
  font: ("Libertinus Serif",),
  heading-family: ("Libertinus Serif",),
  sectionnumbering: "1.1.a",
  mathfont: ("New Computer Modern Math",),
  linkcolor: [\#0000FF],
  toc_title: [Table of contents],
  toc_depth: 3,
  doc,
)

Users of pandas will know about the #NormalTok(".assign()"); method of the DataFrame. But some code using it can look a little mysterious, particularly when #NormalTok("lambda");, #NormalTok("**");, and dictionary comprehensions appear together. In this note, I work through some examples to explain what these pieces do. I ran the examples with pandas 3.1.0.

= Assigning a column
<assigning-a-column>
I borrow the toy data frame below from the #link("https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.assign.html")[pandas documentation].

#block[
#Skylighting(([#ImportTok("import");#NormalTok(" pandas ");#ImportTok("as");#NormalTok(" pd");],
[],
[#NormalTok("df ");#OperatorTok("=");#NormalTok(" pd.DataFrame(");],
[#NormalTok("    {");#StringTok("\"temp_c\"");#NormalTok(": [");#FloatTok("17.0");#NormalTok(", ");#FloatTok("25.0");#NormalTok("]},");],
[#NormalTok("    index");#OperatorTok("=");#NormalTok("[");#StringTok("\"Portland\"");#NormalTok(", ");#StringTok("\"Berkeley\"");#NormalTok("],");],
[#NormalTok(")");],
[#NormalTok("df");],));
#block[
#Skylighting(([#NormalTok("          temp_c");],
[#NormalTok("Portland    17.0");],
[#NormalTok("Berkeley    25.0");],));
]
]
The #NormalTok(".assign()"); method returns a new DataFrame containing the existing columns and any columns we supply. Supplying an existing column name replaces that column in the returned DataFrame. Here I add a #NormalTok("state"); column:

#block[
#Skylighting(([#NormalTok("with_state ");#OperatorTok("=");#NormalTok(" df.assign(state");#OperatorTok("=");#NormalTok("[");#StringTok("\"OR\"");#NormalTok(", ");#StringTok("\"CA\"");#NormalTok("])");],
[#NormalTok("with_state");],));
#block[
#Skylighting(([#NormalTok("          temp_c state");],
[#NormalTok("Portland    17.0    OR");],
[#NormalTok("Berkeley    25.0    CA");],));
]
]
The original DataFrame is unchanged:

#block[
#Skylighting(([#NormalTok("df");],));
#block[
#Skylighting(([#NormalTok("          temp_c");],
[#NormalTok("Portland    17.0");],
[#NormalTok("Berkeley    25.0");],));
]
]
We can make the name #NormalTok("df"); refer to the returned DataFrame:

#block[
#Skylighting(([#NormalTok("df ");#OperatorTok("=");#NormalTok(" df.assign(state");#OperatorTok("=");#NormalTok("[");#StringTok("\"OR\"");#NormalTok(", ");#StringTok("\"CA\"");#NormalTok("])");],));
]
This replaces what the name #NormalTok("df"); refers to; it does not modify the old object. If another name referred to that old DataFrame, it would still see the original data. In contrast, the more traditional assignment below changes the DataFrame that #NormalTok("df"); refers to:

#block[
#Skylighting(([#NormalTok("df[");#StringTok("\"state\"");#NormalTok("] ");#OperatorTok("=");#NormalTok(" [");#StringTok("\"OR\"");#NormalTok(", ");#StringTok("\"CA\"");#NormalTok("]");],));
]
Pandas 3 uses #link("https://pandas.pydata.org/docs/user_guide/copy_on_write.html")[Copy-on-Write], so a new DataFrame can initially share data with the original while behaving as a separate copy. Changing one does not change the other. This does not make DataFrames immutable: direct assignment such as #NormalTok("df[\"state\"] = ..."); still changes the object, and two names referring to that same object still see the same changes.

= Why the lambda?
<why-the-lambda>
The signature #NormalTok(".assign(**kwargs)"); tells us that column names are supplied as keyword arguments. In the example above, the keyword is #NormalTok("state"); and its value is a list. Pandas assigns that list to the new column.

The value can also be a #strong[callable], such as an anonymous function created using #NormalTok("lambda");:

#block[
#Skylighting(([#NormalTok("df.assign(temp_f");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: d[");#StringTok("\"temp_c\"");#NormalTok("] ");#OperatorTok("*");#NormalTok(" ");#DecValTok("9");#NormalTok(" ");#OperatorTok("/");#NormalTok(" ");#DecValTok("5");#NormalTok(" ");#OperatorTok("+");#NormalTok(" ");#DecValTok("32");#NormalTok(")");],));
#block[
#Skylighting(([#NormalTok("          temp_c state  temp_f");],
[#NormalTok("Portland    17.0    OR    62.6");],
[#NormalTok("Berkeley    25.0    CA    77.0");],));
]
]
Here #NormalTok(".assign()"); calls the function with the DataFrame as its argument. The function returns the values for #NormalTok("temp_f");. The name #NormalTok("d"); has no special meaning; I could have used #NormalTok("x"); or another name.

For this simple example, we could calculate those values directly:

#block[
#Skylighting(([#NormalTok("df.assign(temp_f");#OperatorTok("=");#NormalTok("df[");#StringTok("\"temp_c\"");#NormalTok("] ");#OperatorTok("*");#NormalTok(" ");#DecValTok("9");#NormalTok(" ");#OperatorTok("/");#NormalTok(" ");#DecValTok("5");#NormalTok(" ");#OperatorTok("+");#NormalTok(" ");#DecValTok("32");#NormalTok(")");],));
#block[
#Skylighting(([#NormalTok("          temp_c state  temp_f");],
[#NormalTok("Portland    17.0    OR    62.6");],
[#NormalTok("Berkeley    25.0    CA    77.0");],));
]
]
The distinction matters in a pipeline. A callable receives the DataFrame at that point in the pipeline, including columns created in earlier steps. It can even use a column created earlier in the #emph[same] #NormalTok(".assign()"); call:

#block[
#Skylighting(([#NormalTok("temperatures ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    pd.DataFrame({");#StringTok("\"temp_c\"");#NormalTok(": [");#FloatTok("17.0");#NormalTok(", ");#FloatTok("25.0");#NormalTok("]})");],
[#NormalTok("    .assign(");],
[#NormalTok("        temp_f");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: d[");#StringTok("\"temp_c\"");#NormalTok("] ");#OperatorTok("*");#NormalTok(" ");#DecValTok("9");#NormalTok(" ");#OperatorTok("/");#NormalTok(" ");#DecValTok("5");#NormalTok(" ");#OperatorTok("+");#NormalTok(" ");#DecValTok("32");#NormalTok(",");],
[#NormalTok("        temp_k");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: (d[");#StringTok("\"temp_f\"");#NormalTok("] ");#OperatorTok("-");#NormalTok(" ");#DecValTok("32");#NormalTok(") ");#OperatorTok("*");#NormalTok(" ");#DecValTok("5");#NormalTok(" ");#OperatorTok("/");#NormalTok(" ");#DecValTok("9");#NormalTok(" ");#OperatorTok("+");#NormalTok(" ");#FloatTok("273.15");#NormalTok(",");],
[#NormalTok("    )");],
[#NormalTok(")");],
[#NormalTok("temperatures");],));
#block[
#Skylighting(([#NormalTok("   temp_c  temp_f  temp_k");],
[#NormalTok("0    17.0    62.6  290.15");],
[#NormalTok("1    25.0    77.0  298.15");],));
]
]
The keyword arguments are processed in order, so #NormalTok("temp_f"); exists when the second function runs. Using the name #NormalTok("df"); inside these functions would instead refer to whatever object that name happened to identify outside the pipeline.

The documentation also says that a callable should not modify the DataFrame it receives. For example, #NormalTok("lambda d: d.pop(\"temp_c\")"); would remove #NormalTok("temp_c"); while calculating the new column. The point of the callable is to calculate values, not to change the data structure as a side effect.

= Cleaning several columns
<cleaning-several-columns>
Now consider some messier toy data. The temperatures include a #NormalTok("C"); suffix, the areas include units, and the populations include commas.

#block[
#Skylighting(([#NormalTok("raw_data ");#OperatorTok("=");#NormalTok(" {");],
[#NormalTok("    ");#StringTok("\"city\"");#NormalTok(": [");#StringTok("\"Portland\"");#NormalTok(", ");#StringTok("\"Berkeley\"");#NormalTok("],");],
[#NormalTok("    ");#StringTok("\"temp_c\"");#NormalTok(": [");#StringTok("\"17C\"");#NormalTok(", ");#StringTok("\"25C\"");#NormalTok("],");],
[#NormalTok("    ");#StringTok("\"area_land\"");#NormalTok(": [");#StringTok("\"345.73 sq km\"");#NormalTok(", ");#StringTok("\"27.02 sq km\"");#NormalTok("],");],
[#NormalTok("    ");#StringTok("\"area_water\"");#NormalTok(": [");#StringTok("\"29.82 sq km\"");#NormalTok(", ");#StringTok("\"18.71 sq km\"");#NormalTok("],");],
[#NormalTok("    ");#StringTok("\"area_total\"");#NormalTok(": [");#StringTok("\"375.55 sq km\"");#NormalTok(", ");#StringTok("\"45.73 sq km\"");#NormalTok("],");],
[#NormalTok("    ");#StringTok("\"pop\"");#NormalTok(": [");#StringTok("\"652,503\"");#NormalTok(", ");#StringTok("\"124,321\"");#NormalTok("],");],
[#NormalTok("}");],
[],
[#NormalTok("pd.DataFrame(raw_data)");],));
#block[
#Skylighting(([#NormalTok("       city temp_c     area_land   area_water    area_total      pop");],
[#NormalTok("0  Portland    17C  345.73 sq km  29.82 sq km  375.55 sq km  652,503");],
[#NormalTok("1  Berkeley    25C   27.02 sq km  18.71 sq km   45.73 sq km  124,321");],));
]
]
We can clean each column separately:

#block[
#Skylighting(([#NormalTok("clean_explicit ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    pd.DataFrame(raw_data)");],
[#NormalTok("    .assign(");],
[#NormalTok("        temp_c");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: pd.to_numeric(");],
[#NormalTok("            d[");#StringTok("\"temp_c\"");#NormalTok("].");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\"C\"");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("        ),");],
[#NormalTok("        area_land");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: pd.to_numeric(");],
[#NormalTok("            d[");#StringTok("\"area_land\"");#NormalTok("].");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\" sq km\"");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("        ),");],
[#NormalTok("        area_water");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: pd.to_numeric(");],
[#NormalTok("            d[");#StringTok("\"area_water\"");#NormalTok("].");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\" sq km\"");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("        ),");],
[#NormalTok("        area_total");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: pd.to_numeric(");],
[#NormalTok("            d[");#StringTok("\"area_total\"");#NormalTok("].");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\" sq km\"");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("        ),");],
[#NormalTok("        pop");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: pd.to_numeric(");],
[#NormalTok("            d[");#StringTok("\"pop\"");#NormalTok("].");#BuiltInTok("str");#NormalTok(".replace(");#StringTok("\",\"");#NormalTok(", ");#StringTok("\"\"");#NormalTok(", regex");#OperatorTok("=");#VariableTok("False");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("        ),");],
[#NormalTok("    )");],
[#NormalTok(")");],
[#NormalTok("clean_explicit");],));
#block[
#Skylighting(([#NormalTok("       city  temp_c  area_land  area_water  area_total     pop");],
[#NormalTok("0  Portland      17     345.73       29.82      375.55  652503");],
[#NormalTok("1  Berkeley      25      27.02       18.71       45.73  124321");],));
]
]
Ew! That's some ugly code. One improvement is to put the repeated operations into functions. The #NormalTok("errors=\"raise\""); arguments make unexpected non-numeric values cause an error rather than quietly become missing values.

#block[
#Skylighting(([#KeywordTok("def");#NormalTok(" parse_area(s: pd.Series) ");#OperatorTok("->");#NormalTok(" pd.Series:");],
[#NormalTok("    ");#ControlFlowTok("return");#NormalTok(" pd.to_numeric(");],
[#NormalTok("        s.");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\" sq km\"");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("    )");],
[],
[],
[#KeywordTok("def");#NormalTok(" parse_pop(s: pd.Series) ");#OperatorTok("->");#NormalTok(" pd.Series:");],
[#NormalTok("    ");#ControlFlowTok("return");#NormalTok(" pd.to_numeric(");],
[#NormalTok("        s.");#BuiltInTok("str");#NormalTok(".replace(");#StringTok("\",\"");#NormalTok(", ");#StringTok("\"\"");#NormalTok(", regex");#OperatorTok("=");#VariableTok("False");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("    )");],));
]
We can now write:

#block[
#Skylighting(([#NormalTok("clean_helpers ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    pd.DataFrame(raw_data)");],
[#NormalTok("    .assign(");],
[#NormalTok("        temp_c");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: pd.to_numeric(");],
[#NormalTok("            d[");#StringTok("\"temp_c\"");#NormalTok("].");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\"C\"");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("        ),");],
[#NormalTok("        area_land");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: parse_area(d[");#StringTok("\"area_land\"");#NormalTok("]),");],
[#NormalTok("        area_water");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: parse_area(d[");#StringTok("\"area_water\"");#NormalTok("]),");],
[#NormalTok("        area_total");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: parse_area(d[");#StringTok("\"area_total\"");#NormalTok("]),");],
[#NormalTok("        pop");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: parse_pop(d[");#StringTok("\"pop\"");#NormalTok("]),");],
[#NormalTok("    )");],
[#NormalTok(")");],));
]
This is better, but we are still repeating ourselves for the three area columns.

= Unpacking a dictionary of functions
<unpacking-a-dictionary-of-functions>
The three area arguments above can be generated using a dictionary comprehension:

#block[
#Skylighting(([#NormalTok("area_cols ");#OperatorTok("=");#NormalTok(" [");#StringTok("\"area_land\"");#NormalTok(", ");#StringTok("\"area_water\"");#NormalTok(", ");#StringTok("\"area_total\"");#NormalTok("]");],
[],
[#NormalTok("clean_dict ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    pd.DataFrame(raw_data)");],
[#NormalTok("    .assign(");],
[#NormalTok("        temp_c");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: pd.to_numeric(");],
[#NormalTok("            d[");#StringTok("\"temp_c\"");#NormalTok("].");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\"C\"");#NormalTok("), errors");#OperatorTok("=");#StringTok("\"raise\"");],
[#NormalTok("        ),");],
[#NormalTok("        pop");#OperatorTok("=");#KeywordTok("lambda");#NormalTok(" d: parse_pop(d[");#StringTok("\"pop\"");#NormalTok("]),");],
[#NormalTok("        ");#OperatorTok("**");#NormalTok("{c: (");#KeywordTok("lambda");#NormalTok(" d, c");#OperatorTok("=");#NormalTok("c: parse_area(d[c])) ");#ControlFlowTok("for");#NormalTok(" c ");#KeywordTok("in");#NormalTok(" area_cols},");],
[#NormalTok("    )");],
[#NormalTok(")");],));
]
There are two pieces of Python syntax to unpack here. First, the comprehension creates a dictionary whose keys are the area-column names and whose values are functions. The #NormalTok("**"); then #link("https://docs.python.org/3/tutorial/controlflow.html#unpacking-argument-lists")[unpacks that dictionary into keyword arguments]. For example, #NormalTok("**{\"area_land\": some_function}"); supplies the keyword argument #NormalTok("area_land=some_function");.

Second, #NormalTok("c=c"); gives each function its own default value for the column name. That value is set when the function is created. Without it, the functions would look up #NormalTok("c"); when called, by which time the loop would have reached #NormalTok("\"area_total\"");. We would therefore use the total-area values for all three columns. This is a standard #link("https://docs.python.org/3/faq/programming.html#why-do-lambdas-defined-in-a-loop-with-different-values-all-return-the-same-result")[Python closure issue], rather than something specific to pandas.

= A pandas 3 alternative: #NormalTok("pd.col()");
<a-pandas-3-alternative-pd.col>
Pandas 3 introduced #link("https://pandas.pydata.org/docs/whatsnew/v3.0.0.html#initial-support-for-pd-col-syntax-to-create-expressions")[#NormalTok("pd.col()");], which lets us build expressions referring to columns by name. For example, the temperature calculation can be written as:

#block[
#Skylighting(([#NormalTok("df.assign(temp_f");#OperatorTok("=");#NormalTok("pd.col(");#StringTok("\"temp_c\"");#NormalTok(") ");#OperatorTok("*");#NormalTok(" ");#DecValTok("9");#NormalTok(" ");#OperatorTok("/");#NormalTok(" ");#DecValTok("5");#NormalTok(" ");#OperatorTok("+");#NormalTok(" ");#DecValTok("32");#NormalTok(")");],));
#block[
#Skylighting(([#NormalTok("          temp_c state  temp_f");],
[#NormalTok("Portland    17.0    OR    62.6");],
[#NormalTok("Berkeley    25.0    CA    77.0");],));
]
]
The expression is evaluated against the DataFrame supplied by #NormalTok(".assign()");. It therefore serves the same purpose as #NormalTok("lambda d: d[\"temp_c\"] * 9 / 5 + 32");.

Expressions can also use Series methods. Here #NormalTok(".pipe(parse_area)"); passes the selected Series to #NormalTok("parse_area()"); when the expression is evaluated:

#block[
#Skylighting(([#NormalTok("clean_expr ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    pd.DataFrame(raw_data)");],
[#NormalTok("    .assign(");],
[#NormalTok("        temp_c");#OperatorTok("=");#NormalTok("pd.col(");#StringTok("\"temp_c\"");#NormalTok(").");#BuiltInTok("str");#NormalTok(".removesuffix(");#StringTok("\"C\"");#NormalTok(").pipe(pd.to_numeric),");],
[#NormalTok("        pop");#OperatorTok("=");#NormalTok("pd.col(");#StringTok("\"pop\"");#NormalTok(").pipe(parse_pop),");],
[#NormalTok("        ");#OperatorTok("**");#NormalTok("{c: pd.col(c).pipe(parse_area) ");#ControlFlowTok("for");#NormalTok(" c ");#KeywordTok("in");#NormalTok(" area_cols},");],
[#NormalTok("    )");],
[#NormalTok(")");],
[#NormalTok("clean_expr");],));
#block[
#Skylighting(([#NormalTok("       city  temp_c  area_land  area_water  area_total     pop");],
[#NormalTok("0  Portland      17     345.73       29.82      375.55  652503");],
[#NormalTok("1  Berkeley      25      27.02       18.71       45.73  124321");],));
]
]
Each expression records its column name when it is constructed, so there is no #NormalTok("c=c"); to explain in this version. I find this easier to read, though understanding the callable version is still useful when reading existing pandas code.

= Something like #NormalTok("across()");
<something-like-across>
R users might wonder why we are working so hard. Using #NormalTok("dplyr"); and #NormalTok("readr");, the cleaning can be written as follows:

#block[
#Skylighting(([#FunctionTok("library");#NormalTok("(dplyr)");],
[#FunctionTok("library");#NormalTok("(readr)");],
[],
[#NormalTok("raw_data_r ");#OtherTok("<-");#NormalTok(" ");#FunctionTok("list");#NormalTok("(");],
[#NormalTok("  ");#AttributeTok("city =");#NormalTok(" ");#FunctionTok("c");#NormalTok("(");#StringTok("\"Portland\"");#NormalTok(", ");#StringTok("\"Berkeley\"");#NormalTok("),");],
[#NormalTok("  ");#AttributeTok("temp_c =");#NormalTok(" ");#FunctionTok("c");#NormalTok("(");#StringTok("\"17C\"");#NormalTok(", ");#StringTok("\"25C\"");#NormalTok("),");],
[#NormalTok("  ");#AttributeTok("area_land =");#NormalTok(" ");#FunctionTok("c");#NormalTok("(");#StringTok("\"345.73 sq km\"");#NormalTok(", ");#StringTok("\"27.02 sq km\"");#NormalTok("),");],
[#NormalTok("  ");#AttributeTok("area_water =");#NormalTok(" ");#FunctionTok("c");#NormalTok("(");#StringTok("\"29.82 sq km\"");#NormalTok(", ");#StringTok("\"18.71 sq km\"");#NormalTok("),");],
[#NormalTok("  ");#AttributeTok("area_total =");#NormalTok(" ");#FunctionTok("c");#NormalTok("(");#StringTok("\"375.55 sq km\"");#NormalTok(", ");#StringTok("\"45.73 sq km\"");#NormalTok("),");],
[#NormalTok("  ");#AttributeTok("pop =");#NormalTok(" ");#FunctionTok("c");#NormalTok("(");#StringTok("\"652,503\"");#NormalTok(", ");#StringTok("\"124,321\"");#NormalTok(")");],
[#NormalTok(")");],
[],
[#NormalTok("clean_r ");#OtherTok("<-");],
[#NormalTok("  tibble");#SpecialCharTok("::");#FunctionTok("as_tibble");#NormalTok("(raw_data_r) ");#SpecialCharTok("|>");],
[#NormalTok("  ");#FunctionTok("mutate");#NormalTok("(");#FunctionTok("across");#NormalTok("(");#SpecialCharTok("-");#NormalTok("city, parse_number))");],
[],
[#NormalTok("clean_r");],));
#block[
#Skylighting(([#NormalTok("# A tibble: 2 × 6");],
[#NormalTok("  city     temp_c area_land area_water area_total    pop");],
[#NormalTok("  <chr>     <dbl>     <dbl>      <dbl>      <dbl>  <dbl>");],
[#NormalTok("1 Portland     17    345.73      29.82     375.55 652503");],
[#NormalTok("2 Berkeley     25     27.02      18.71      45.73 124321");],));
]
]
The #NormalTok("across()"); call applies #NormalTok("parse_number()"); to every column except #NormalTok("city");. The parser handles the units and commas in these values.

For this particular data set, we can write a small Python helper that removes everything except digits, decimal points, and minus signs before converting to numbers:

#block[
#Skylighting(([#KeywordTok("def");#NormalTok(" parse_number(s: pd.Series) ");#OperatorTok("->");#NormalTok(" pd.Series:");],
[#NormalTok("    ");#ControlFlowTok("return");#NormalTok(" (");],
[#NormalTok("        s.astype(");#StringTok("\"string\"");#NormalTok(")");],
[#NormalTok("        .");#BuiltInTok("str");#NormalTok(".replace(");#VerbatimStringTok("r\"");#PreprocessorTok("[^");#DecValTok("\\d");#PreprocessorTok(".");#CharTok("\\-");#PreprocessorTok("]");#OperatorTok("+");#VerbatimStringTok("\"");#NormalTok(", ");#StringTok("\"\"");#NormalTok(", regex");#OperatorTok("=");#VariableTok("True");#NormalTok(")");],
[#NormalTok("        .pipe(pd.to_numeric, errors");#OperatorTok("=");#StringTok("\"raise\"");#NormalTok(")");],
[#NormalTok("    )");],));
]
This is not a general replacement for #NormalTok("readr::parse_number()");. For example, it would turn #NormalTok("\"12 to 15\""); into #NormalTok("1215"); and would not correctly interpret scientific notation. It is suitable here because we know the limited formats used in our toy data.

To select columns from the current DataFrame, I use #link("https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.pipe.html")[#NormalTok(".pipe()");]. It passes that DataFrame to a function; here, the function calls #NormalTok(".assign()"); with a generated argument for every column except #NormalTok("city");.

#block[
#Skylighting(([#NormalTok("clean_all ");#OperatorTok("=");#NormalTok(" (");],
[#NormalTok("    pd.DataFrame(raw_data)");],
[#NormalTok("    .pipe(");],
[#NormalTok("        ");#KeywordTok("lambda");#NormalTok(" d: d.assign(");],
[#NormalTok("            ");#OperatorTok("**");#NormalTok("{");],
[#NormalTok("                c: pd.col(c).pipe(parse_number)");],
[#NormalTok("                ");#ControlFlowTok("for");#NormalTok(" c ");#KeywordTok("in");#NormalTok(" d.columns ");#ControlFlowTok("if");#NormalTok(" c ");#OperatorTok("!=");#NormalTok(" ");#StringTok("\"city\"");],
[#NormalTok("            }");],
[#NormalTok("        )");],
[#NormalTok("    )");],
[#NormalTok("    .assign(");],
[#NormalTok("        temp_f");#OperatorTok("=");#NormalTok("pd.col(");#StringTok("\"temp_c\"");#NormalTok(") ");#OperatorTok("*");#NormalTok(" ");#DecValTok("9");#NormalTok(" ");#OperatorTok("/");#NormalTok(" ");#DecValTok("5");#NormalTok(" ");#OperatorTok("+");#NormalTok(" ");#DecValTok("32");#NormalTok(",");],
[#NormalTok("        temp_k");#OperatorTok("=");#NormalTok("(pd.col(");#StringTok("\"temp_f\"");#NormalTok(") ");#OperatorTok("-");#NormalTok(" ");#DecValTok("32");#NormalTok(") ");#OperatorTok("*");#NormalTok(" ");#DecValTok("5");#NormalTok(" ");#OperatorTok("/");#NormalTok(" ");#DecValTok("9");#NormalTok(" ");#OperatorTok("+");#NormalTok(" ");#FloatTok("273.15");#NormalTok(",");],
[#NormalTok("    )");],
[#NormalTok(")");],
[#NormalTok("clean_all[[");#StringTok("\"city\"");#NormalTok(", ");#StringTok("\"temp_c\"");#NormalTok(", ");#StringTok("\"temp_f\"");#NormalTok(", ");#StringTok("\"temp_k\"");#NormalTok("]]");],));
#block[
#Skylighting(([#NormalTok("       city  temp_c  temp_f  temp_k");],
[#NormalTok("0  Portland      17    62.6  290.15");],
[#NormalTok("1  Berkeley      25    77.0  298.15");],));
]
]
The output shows the temperature columns; the other cleaned columns remain in #NormalTok("clean_all");. The last #NormalTok(".assign()"); illustrates the point about evaluation order again: the expression for #NormalTok("temp_k"); uses the newly created #NormalTok("temp_f");.

= Some choices
<some-choices>
For one or two columns, spelling out the arguments to #NormalTok(".assign()"); is often clearest. When several columns need the same treatment, a dictionary comprehension can avoid repetition. Callables let those calculations use the DataFrame at the current step in a pipeline, and pandas 3's #NormalTok("pd.col()"); expressions can make some of them easier to read.

The goal is readable code. A pipeline is useful when it makes the sequence of transformations easier to follow; there is no need to put an entire analysis into one expression.
