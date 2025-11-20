import { Link } from 'wouter'
import { useNewsList } from '../hooks/useNews'
import { Database, Calendar, FileText, ExternalLink, Hash, ChevronLeft, ChevronRight, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react'
import { useState } from 'react'

export default function NewsList() {
    const [page, setPage] = useState(1)
    const [sortBy, setSortBy] = useState('publication_date')
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
    const pageSize = 50

    const { news, totalCount, totalFacts, loading, error } = useNewsList(page, pageSize, sortBy, sortOrder)

    const totalPages = Math.ceil(totalCount / pageSize)

    const handleSort = (column: string) => {
        if (sortBy === column) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
        } else {
            setSortBy(column)
            setSortOrder('desc') // Default to desc for new columns
        }
    }

    const SortIcon = ({ column }: { column: string }) => {
        if (sortBy !== column) return <ArrowUpDown size={12} className="text-gray-300" />
        return sortOrder === 'asc' ? <ArrowUp size={12} className="text-blue-600" /> : <ArrowDown size={12} className="text-blue-600" />
    }

    if (loading && page === 1) return <div className="loading-state">Loading data...</div>
    if (error) return <div className="error-state">Error: {error}</div>

    return (
        <div className="container" style={{ padding: '2rem' }}>
            <div className="sb-header">
                <div className="sb-header-title">news_urls</div>
                <div className="text-xs text-muted font-mono">
                    {totalCount} records &bull; {totalFacts} facts &bull; Page {page} of {totalPages || 1}
                </div>
            </div>

            <div className="sb-table-container">
                <div className="overflow-x-auto">
                    <table className="sb-table">
                        <thead>
                            <tr>
                                <th style={{ width: '80px', cursor: 'pointer' }} onClick={() => handleSort('id')}>
                                    <div className="cell-text hover:text-blue-600 transition-colors">
                                        <Hash size={14} /> ID <SortIcon column="id" />
                                    </div>
                                </th>
                                <th style={{ width: '180px', cursor: 'pointer' }} onClick={() => handleSort('source_name')}>
                                    <div className="cell-text hover:text-blue-600 transition-colors">
                                        <Database size={14} /> Source <SortIcon column="source_name" />
                                    </div>
                                </th>
                                <th style={{ width: '140px', cursor: 'pointer' }} onClick={() => handleSort('publication_date')}>
                                    <div className="cell-text hover:text-blue-600 transition-colors">
                                        <Calendar size={14} /> Date <SortIcon column="publication_date" />
                                    </div>
                                </th>
                                <th style={{ cursor: 'pointer' }} onClick={() => handleSort('title')}>
                                    <div className="cell-text hover:text-blue-600 transition-colors">
                                        <FileText size={14} /> Headline <SortIcon column="title" />
                                    </div>
                                </th>
                                <th style={{ width: '100px' }}>
                                    <div className="cell-text"><Hash size={14} /> Facts</div>
                                </th>
                                <th style={{ width: '80px' }}></th>
                            </tr>
                        </thead>
                        <tbody className={loading ? 'opacity-50' : ''}>
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

            <div className="flex items-center justify-between mt-4" style={{ padding: '0 0.5rem' }}>
                <div className="text-xs text-muted">
                    Showing <span className="font-medium text-gray-900">{(page - 1) * pageSize + 1}</span> to <span className="font-medium text-gray-900">{Math.min(page * pageSize, totalCount)}</span> of <span className="font-medium text-gray-900">{totalCount}</span> entries
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page === 1 || loading}
                        className="sb-btn"
                    >
                        <ChevronLeft size={14} /> Previous
                    </button>
                    <button
                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                        disabled={page >= totalPages || loading}
                        className="sb-btn"
                    >
                        Next <ChevronRight size={14} />
                    </button>
                </div>
            </div>
        </div>
    )
}
