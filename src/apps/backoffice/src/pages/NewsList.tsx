import { Link } from 'wouter'
import { useNewsList } from '../hooks/useNews'
import { Database, Calendar, FileText, ExternalLink, Hash } from 'lucide-react'

export default function NewsList() {
    const { news, loading, error } = useNewsList()

    if (loading) return <div className="loading-state">Loading data...</div>
    if (error) return <div className="error-state">Error: {error}</div>

    return (
        <div className="container" style={{ padding: '2rem' }}>
            <div className="sb-header">
                <div className="sb-header-title">news_urls</div>
                <div className="text-xs text-muted font-mono">{news.length} records</div>
            </div>

            <div className="sb-table-container">
                <table className="sb-table">
                    <thead>
                        <tr>
                            <th style={{ width: '60px' }}>
                                <div className="cell-text"><Hash size={14} /> ID</div>
                            </th>
                            <th style={{ width: '180px' }}>
                                <div className="cell-text"><Database size={14} /> Source</div>
                            </th>
                            <th style={{ width: '140px' }}>
                                <div className="cell-text"><Calendar size={14} /> Date</div>
                            </th>
                            <th>
                                <div className="cell-text"><FileText size={14} /> Headline</div>
                            </th>
                            <th style={{ width: '100px' }}>
                                <div className="cell-text"><Hash size={14} /> Facts</div>
                            </th>
                            <th style={{ width: '80px' }}></th>
                        </tr>
                    </thead>
                    <tbody>
                        {news.map((item) => (
                            <tr key={item.id}>
                                <td>
                                    <span className="cell-mono" title={item.id}>{item.id.slice(0, 4)}...</span>
                                </td>
                                <td>
                                    <div className="cell-text">
                                        <span className="cell-badge">{item.source_name || 'Unknown'}</span>
                                    </div>
                                </td>
                                <td className="cell-mono">
                                    {item.publication_date
                                        ? new Date(item.publication_date).toLocaleDateString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit' })
                                        : '-'}
                                </td>
                                <td>
                                    <Link href={`/news/${item.id}`} className="hover:text-blue-600 hover:underline" title={item.title || item.url}>
                                        {item.title || item.url}
                                    </Link>
                                </td>
                                <td>
                                    <span className={`cell-mono ${item.facts_count ? 'text-green-600' : 'text-gray-400'}`}>
                                        {item.facts_count || 0}
                                    </span>
                                </td>
                                <td style={{ textAlign: 'center' }}>
                                    <Link href={`/news/${item.id}`} className="icon-subtle hover:text-blue-600">
                                        <ExternalLink size={14} />
                                    </Link>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
