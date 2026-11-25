import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const visited = new Set()
const failures = []
const han = /[\u3400-\u9fff]/
const textKinds = new Set([
  ts.SyntaxKind.StringLiteral, ts.SyntaxKind.JsxText,
  ts.SyntaxKind.NoSubstitutionTemplateLiteral, ts.SyntaxKind.TemplateHead,
  ts.SyntaxKind.TemplateMiddle, ts.SyntaxKind.TemplateTail,
])

function inspect(file) {
  if (visited.has(file)) return
  visited.add(file)
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true,
    file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  function visit(node) {
    if (textKinds.has(node.kind) && han.test(node.text)) {
      // Translation dictionary keys and log messages are not interface text.
      let internal = ts.isPropertyAssignment(node.parent) && node.parent.name === node
      for (let parent = node.parent; parent; parent = parent.parent) {
        if (ts.isCallExpression(parent) && parent.expression.getText(source).startsWith('console.')) internal = true
      }
      if (!internal) {
        const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
        failures.push(`${path.relative(root, file)}:${line}: ${node.text.trim()}`)
      }
    }
    if (ts.isImportDeclaration(node) && node.moduleSpecifier.text.startsWith('.')) {
      const base = path.resolve(path.dirname(file), node.moduleSpecifier.text)
      const dependency = [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`]
        .find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile())
      if (dependency && /\.tsx?$/.test(dependency)) inspect(dependency)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
}

inspect(path.join(root, 'src/main.tsx'))
assert.equal(failures.length, 0, `Untranslated interface text:\n${failures.join('\n')}`)
assert.match(fs.readFileSync(path.join(root, 'index.html'), 'utf8'), /<html lang="en">/)

const labelsSource = fs.readFileSync(path.join(root, 'src/utils/englishUi.ts'), 'utf8')
const labelsJs = ts.transpileModule(labelsSource, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { categoryLabels, whisperLabels, englishSystemText } = await import(`data:text/javascript;base64,${Buffer.from(labelsJs).toString('base64')}`)
assert.ok(Object.values(categoryLabels).every(item => !han.test(item.name + item.description)))
assert.ok(Object.values(whisperLabels).every(item => !han.test(item.description + item.accuracy + item.speed)))
assert.equal(englishSystemText('视频处理流水线'), 'Video processing pipeline')
assert.equal(englishSystemText('My original video title'), 'My original video title')
assert.equal(englishSystemText('我的视频标题'), '我的视频标题')
console.log(`English UI check passed across ${visited.size} source files. User content is preserved.`)
