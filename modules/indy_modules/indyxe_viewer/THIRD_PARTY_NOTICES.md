# indyxe_viewer — 第三者ソフトウェアの帰属表示

## デジタル庁デザインシステム（DADS）デザイントークン
- **上流**: https://github.com/digital-go-jp/design-tokens （npm: `@digital-go-jp/design-tokens` v2.1.0）
- **ライセンス**: MIT License
- **使用箇所**: `static/app.css` 冒頭の CSS 変数（使用する値のみ抜粋）
- **ライセンス本文**:

```
MIT License

Copyright (c) 2023 デジタル庁

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Python 実行時依存
`pyproject.toml` / `uv.lock` に定義し、`uv sync` で取得する（本ディレクトリには同梱しない）。
pyindy は本リポジトリの `modules/pyindy` を参照する。
