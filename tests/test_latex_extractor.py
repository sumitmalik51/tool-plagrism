"""Tests for LaTeX text extraction."""

import pytest
from app.tools.content_extractor_tool import _extract_from_latex


def _latex_text(source: str) -> str:
    text, truncated = _extract_from_latex(source.encode("utf-8"))
    assert truncated is False
    return text


class TestLatexExtraction:
    """Tests for LaTeX file text extraction."""

    def test_basic_latex_extraction(self):
        latex = r"""
\documentclass{article}
\usepackage{amsmath}
\begin{document}
\title{My Research Paper}
\author{John Doe}

\section{Introduction}
This is the introduction to the paper.

\section{Methodology}
We used a novel approach based on \textbf{deep learning} and \textit{transfer learning}.

\end{document}
"""
        result = _latex_text(latex)
        assert "introduction to the paper" in result.lower()
        assert "deep learning" in result
        assert "transfer learning" in result
        assert "\\documentclass" not in result
        assert "\\usepackage" not in result

    def test_citations_preserved_as_text(self):
        latex = r"""
\begin{document}
Previous work \cite{Smith2020} has shown that results vary \citep{Doe2021}.
\end{document}
"""
        result = _latex_text(latex)
        assert "Smith2020" in result
        assert "Doe2021" in result

    def test_math_equations_handled(self):
        latex = r"""
\begin{document}
The formula $E = mc^2$ is famous.
Complex equation:
$$\int_0^1 x^2 dx = \frac{1}{3}$$
\end{document}
"""
        result = _latex_text(latex)
        assert "E = mc^2" in result
        assert "[equation]" in result

    def test_comments_removed(self):
        latex = r"""
\begin{document}
% This is a comment
Visible text here.
Another line. % inline comment
\end{document}
"""
        result = _latex_text(latex)
        assert "Visible text here" in result
        assert "This is a comment" not in result

    def test_formatting_commands_stripped(self):
        latex = r"""
\begin{document}
\textbf{Bold text} and \textit{italic text} and \emph{emphasized}.
\end{document}
"""
        result = _latex_text(latex)
        assert "Bold text" in result
        assert "italic text" in result
        assert "emphasized" in result
        assert "\\textbf" not in result

    def test_empty_latex(self):
        latex = r"""
\documentclass{article}
\begin{document}
\end{document}
"""
        result = _latex_text(latex)
        # Should be mostly empty after stripping commands
        assert len(result.strip()) < 10

    def test_section_titles_preserved(self):
        latex = r"""
\begin{document}
\section{Background}
Some background information.
\subsection{Related Work}
Related work details.
\end{document}
"""
        result = _latex_text(latex)
        assert "Background" in result
        assert "Related Work" in result
        assert "Some background" in result
