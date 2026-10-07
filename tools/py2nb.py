"""Convierte un script con marcas de celda ("# %%" código, "# %% [markdown]" texto) en un notebook .ipynb.

Uso:  python tools/py2nb.py notebooks/src/02_modelo_milp.py notebooks/02_modelo_milp.ipynb
Las celdas markdown se escriben como comentarios que empiezan con "# " y se les quita ese prefijo.
"""
import sys
import nbformat as nbf


def convertir(src, dst):
    texto = open(src, encoding="utf-8").read()
    celdas, actual, tipo = [], [], None
    for linea in texto.splitlines():
        if linea.startswith("# %%"):
            if tipo is not None:
                celdas.append((tipo, actual))
            tipo = "markdown" if "[markdown]" in linea else "code"
            actual = []
            continue
        if tipo is None:
            continue
        actual.append(linea)
    if tipo is not None:
        celdas.append((tipo, actual))

    nb = nbf.v4.new_notebook()
    for tipo, lineas in celdas:
        while lineas and not lineas[-1].strip():
            lineas.pop()
        while lineas and not lineas[0].strip():
            lineas.pop(0)
        if tipo == "markdown":
            cuerpo = "\n".join(l[2:] if l.startswith("# ") else l[1:] if l.startswith("#") else l for l in lineas)
            nb.cells.append(nbf.v4.new_markdown_cell(cuerpo))
        else:
            nb.cells.append(nbf.v4.new_code_cell("\n".join(lineas)))
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.metadata["language_info"] = {"name": "python"}
    nbf.write(nb, dst)
    print(f"{dst}: {len(nb.cells)} celdas")


if __name__ == "__main__":
    convertir(sys.argv[1], sys.argv[2])
