/**
 * テンプレート変数ユーティリティ
 *
 * {{variable_name}} 形式のテキスト変数と、独立したファイル添付変数を扱うヘルパー関数群
 */

import { TemplateVariable } from './savedPrompts'

const VARIABLE_PATTERN = /\{\{(\w+)\}\}/g

/**
 * テンプレート文字列からテキスト変数名を抽出する
 */
export function extractVariableNames(content: string): string[] {
  const names = new Set<string>()
  let match: RegExpExecArray | null
  while ((match = VARIABLE_PATTERN.exec(content)) !== null) {
    names.add(match[1])
  }
  return Array.from(names)
}

/**
 * テンプレート内の変数を実際の値で置換する
 */
export function resolveTemplate(content: string, values: Record<string, string>): string {
  return content.replace(VARIABLE_PATTERN, (_, name) => values[name] ?? `{{${name}}}`)
}

/**
 * テンプレート内容の変更に合わせてテキスト変数リストを同期する
 *
 * - テンプレート内容の {{var}} から検出されたテキスト変数を同期
 * - ファイル型変数はテンプレート内容に依存しないので常に保持
 * - 新しく追加されたテキスト変数はデフォルトメタデータで作成
 * - テンプレート内容から消えたテキスト変数は除去
 */
export function syncVariables(
  content: string,
  existingVars: TemplateVariable[]
): TemplateVariable[] {
  const names = extractVariableNames(content)
  const existingMap = new Map(existingVars.map((v) => [v.name, v]))

  // テンプレート内容から検出されたテキスト変数
  const textVars = names.map((name) => {
    const existing = existingMap.get(name)
    if (existing) return existing
    return {
      name,
      label: name,
      description: '',
      defaultValue: '',
    }
  })

  // ファイル型変数はテンプレート内容に依存しないので常に保持
  const fileVars = existingVars.filter((v) => v.type === 'file')

  return [...textVars, ...fileVars]
}
