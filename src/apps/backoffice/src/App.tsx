import { Link, Route, Switch, useLocation } from 'wouter'
import { Compass, ListChecks } from 'lucide-react'
import KnowledgeGraph from './pages/KnowledgeGraph'
import NewsList from './pages/NewsList'
import NewsDetail from './pages/NewsDetail'
import './App.css'

function App() {
  const [location] = useLocation()

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="container">
          <div className="branding">
            <img src="/src/assets/logo.png" alt="T4L logo" className="app-logo" />
            <div className="app-title">
              <span>Backoffice</span>
              <small>Loss Intelligence</small>
            </div>
          </div>
          <nav className="nav-links">
            <Link href="/graph" className={`nav-link ${location.startsWith('/graph') || location === '/' ? 'active' : ''}`}>
              <Compass size={16} /> Knowledge Graph
            </Link>
            <Link href="/news" className={`nav-link ${location.startsWith('/news') ? 'active' : ''}`}>
              <ListChecks size={16} /> News Validator
            </Link>
          </nav>
        </div>
      </header>
      <main className="app-main">
        <Switch>
          <Route path="/" component={KnowledgeGraph} />
          <Route path="/graph" component={KnowledgeGraph} />
          <Route path="/news" component={NewsList} />
          <Route path="/news/:id" component={NewsDetail} />
          <Route>404: No such page!</Route>
        </Switch>
      </main>
    </div>
  )
}

export default App
