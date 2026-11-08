import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import './index.css';
import { connectHost } from './host';

createRoot(document.getElementById('root')!).render(<App />);
void connectHost();
