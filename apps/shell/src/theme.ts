// Node/source type colors — shared by GraphOverlay and source chips.
export const TYPE_COLOR: Record<string, string> = {
  Company: '#FFD21E',
  Product: '#A78BFA',
  Decision: '#F97316',
  Document: '#8C8C94',
  Person: '#60A5FA',
  FundingProgram: '#36C399',
  Lead: '#EC4899',
  Thought: '#FBBF24',
  Area: '#36C399',
  Compliance: '#2DD4BF',
}

export const typeColor = (t?: string): string => (t && TYPE_COLOR[t]) || '#8C8C94'
