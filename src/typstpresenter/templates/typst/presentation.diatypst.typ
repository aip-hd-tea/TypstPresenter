#import "@preview/diatypst:0.9.1": *
#show: slides.with(
  title: [{{ presentation.title | express }}]
)

#set heading(numbering: none)

{% for slide in presentation %}
== {{ slide.title | express }}

{{ slide.content | express }}
{% endfor %}
