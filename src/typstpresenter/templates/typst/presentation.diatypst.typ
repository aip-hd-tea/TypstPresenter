#import "@preview/diatypst:0.9.1": *
#show slides.with(
  title: "TODO"
)

{% for slide in presentation %}
- {{ slide.title }} {# TODO #}
{% endfor %}
