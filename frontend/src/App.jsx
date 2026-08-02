import { useState } from 'react'
import axios from 'axios'
import './App.css'

function App() {
  const [command, setCommand] = useState('')
  const [editInstruction, setEditInstruction] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState('')

  const handleGenerate = async () => {
    if (!command.trim()) {
      setError('Please enter a command first.')
      return
    }
    setError('')
    setResult(null)
    setLoading(true)

    try {
      const response = await axios.post('http://localhost:8000/generate', { command })
      setResult({ subject: response.data.subject, body: response.data.body })
      setProfile(response.data.profile)
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleRevise = async () => {
    if (!editInstruction.trim() || !result || !profile) return
    setError('')
    setLoading(true)

    try {
      const response = await axios.post('http://localhost:8000/revise', {
        profile: profile,
        current_email: result,
        edit_instruction: editInstruction
      })
      setResult(response.data)
      setEditInstruction('')
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-container">
      <h1>Email Generator</h1>
      <p className="subtitle">
        Tell it what to do — e.g. "generate a discount email from https://example.com"
      </p>

      <textarea
        className="command-input"
        placeholder="Type your command here..."
        value={command}
        onChange={(e) => setCommand(e.target.value)}
        rows={3}
      />

      <button onClick={handleGenerate} disabled={loading}>
        {loading ? 'Generating...' : 'Generate'}
      </button>

      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <div className="result">
            <h2>{result.subject}</h2>
            <div dangerouslySetInnerHTML={{ __html: result.body }} />
          </div>

          <div className="edit-box">
            <textarea
              className="command-input"
              placeholder='Request a change, e.g. "make it shorter" or "remove the second image"'
              value={editInstruction}
              onChange={(e) => setEditInstruction(e.target.value)}
              rows={2}
            />
            <button onClick={handleRevise} disabled={loading}>
              {loading ? 'Updating...' : 'Apply Edit'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export default App