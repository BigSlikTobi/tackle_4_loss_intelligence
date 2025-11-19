
import { createClient } from '@supabase/supabase-js'
import dotenv from 'dotenv'
import path from 'path'

// Load env vars
dotenv.config({ path: path.resolve(process.cwd(), '.env') })

const supabaseUrl = process.env.VITE_SUPABASE_URL
const supabaseKey = process.env.VITE_SUPABASE_KEY

if (!supabaseUrl || !supabaseKey) {
    console.error('Missing Supabase environment variables')
    process.exit(1)
}

const supabase = createClient(supabaseUrl, supabaseKey)

async function testQuery() {
    console.log('Testing query with facts_count filter...')
    const { data, error } = await supabase
        .from('news_urls')
        .select('*')
        .gt('facts_count', 0)
        .limit(1)

    if (error) {
        console.error('Error with facts_count filter:', error)
    } else {
        console.log('Success with facts_count filter:', data)
    }

    console.log('\nTesting query WITHOUT filter to check schema...')
    const { data: data2, error: error2 } = await supabase
        .from('news_urls')
        .select('*')
        .limit(1)

    if (error2) {
        console.error('Error fetching news_urls:', error2)
    } else {
        console.log('Sample record keys:', Object.keys(data2[0] || {}))
    }
}

testQuery()
