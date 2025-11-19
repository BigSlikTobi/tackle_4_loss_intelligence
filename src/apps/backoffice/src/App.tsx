import { Route, Switch } from 'wouter'
import NewsList from './pages/NewsList'
import NewsDetail from './pages/NewsDetail'
import './App.css'

function App() {
  return (
    <div className="app-container">
      <header className="app-header">
        <div className="container">
          <img src="/src/assets/logo.png" alt="T4L logo" className="app-logo" />
          <h1>Knowledge Extraction Validator</h1>
        </div>
      </header>
      <main className="app-main">
        <Switch>
          <Route path="/" component={NewsList} />
          <Route path="/news/:id" component={NewsDetail} />
          <Route>404: No such page!</Route>
        </Switch>
      </main>
    </div>
  )
}

export default App
