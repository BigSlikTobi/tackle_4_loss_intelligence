import { useRoute, Link } from 'wouter'
import { useNewsDetail } from '../hooks/useNews'
import { ArrowLeft, Calendar, Database, Tag, Hash, AlignLeft, Users } from 'lucide-react'

export default function NewsDetail() {
    const [, params] = useRoute('/news/:id')
    const id = params?.id || ''
    const { newsDetail, loading, error } = useNewsDetail(id)

    if (loading) return <div className="loading-state">Loading details...</div>
    if (error) return <div className="error-state">Error: {error}</div>
    if (!newsDetail) return <div className="container" style={{ padding: '2rem' }}>News not found</div>

    return (
        <div className="container" style={{ padding: '2rem' }}>
            <div className="mb-6">
                <Link href="/" className="text-xs text-muted hover:text-blue-600 flex items-center gap-1 mb-4 font-mono">
                    <ArrowLeft size={12} /> BACK TO LIST
                </Link>

                <div className="sb-table-container mb-8">
                    <div className="sb-header">
                        <div className="sb-header-title">news_url_details</div>
                        <div className="text-xs text-muted font-mono">{id}</div>
                    </div>
                    <table className="sb-table">
                        <tbody>
                            <tr>
                                <td style={{ width: '150px', backgroundColor: 'var(--bg-surface-200)', color: 'var(--text-subtle)' }}>Headline</td>
                                <td style={{ fontWeight: 500 }}>{newsDetail.title || newsDetail.url}</td>
                            </tr>
                            <tr>
                                <td style={{ backgroundColor: 'var(--bg-surface-200)', color: 'var(--text-subtle)' }}>Source</td>
                                <td>
                                    <div className="cell-text">
                                        <Database size={14} className="icon-subtle" />
                                        <span className="cell-badge">{newsDetail.source_name || 'Unknown'}</span>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td style={{ backgroundColor: 'var(--bg-surface-200)', color: 'var(--text-subtle)' }}>Date</td>
                                <td className="cell-mono">
                                    {newsDetail.publication_date ? new Date(newsDetail.publication_date).toLocaleDateString() : '-'}
                                </td>
                            </tr>
                            <tr>
                                <td style={{ backgroundColor: 'var(--bg-surface-200)', color: 'var(--text-subtle)' }}>Description</td>
                                <td style={{ whiteSpace: 'normal', lineHeight: '1.6', padding: '1rem' }}>
                                    {newsDetail.description || 'No description available.'}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>

                <div className="sb-header" style={{ border: '1px solid var(--border-default)', borderBottom: 'none', borderRadius: '4px 4px 0 0' }}>
                    <div className="sb-header-title">extracted_facts</div>
                    <div className="text-xs text-muted font-mono">{newsDetail.facts.length} rows</div>
                </div>

                <div className="sb-table-container" style={{ borderRadius: '0 0 4px 4px' }}>
                    <table className="sb-table">
                        <thead>
                            <tr>
                                <th style={{ width: '50%' }}>
                                    <div className="cell-text"><AlignLeft size={14} /> Fact Text</div>
                                </th>
                                <th style={{ width: '25%' }}>
                                    <div className="cell-text"><Hash size={14} /> Topics</div>
                                </th>
                                <th style={{ width: '25%' }}>
                                    <div className="cell-text"><Users size={14} /> Entities</div>
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {newsDetail.facts.map((fact) => (
                                <tr key={fact.id}>
                                    <td style={{ whiteSpace: 'normal', verticalAlign: 'top', lineHeight: '1.5' }}>
                                        {fact.fact_text}
                                    </td>
                                    <td style={{ verticalAlign: 'top', whiteSpace: 'normal' }}>
                                        <div className="flex flex-wrap gap-2">
                                            {fact.topics && fact.topics.length > 0 ? (
                                                fact.topics.map((topic, i) => (
                                                    <span key={i} className="cell-badge" style={{ background: '#f3e8ff', borderColor: '#d8b4fe', color: '#6b21a8' }}>
                                                        {topic.canonical_topic}
                                                    </span>
                                                ))
                                            ) : (
                                                <span className="text-xs text-muted italic">null</span>
                                            )}
                                        </div>
                                    </td>
                                    <td style={{ verticalAlign: 'top', whiteSpace: 'normal' }}>
                                        <div className="flex flex-wrap gap-2">
                                            {fact.entities && fact.entities.length > 0 ? (
                                                fact.entities.map((entity) => (
                                                    <span key={entity.id} className="cell-badge" style={{
                                                        background: entity.entity_type === 'player' ? '#eff6ff' : '#ecfdf5',
                                                        borderColor: entity.entity_type === 'player' ? '#bfdbfe' : '#6ee7b7',
                                                        color: entity.entity_type === 'player' ? '#1e40af' : '#047857'
                                                    }}>
                                                        {entity.matched_name || entity.mention_text}
                                                    </span>
                                                ))
                                            ) : (
                                                <span className="text-xs text-muted italic">null</span>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}
