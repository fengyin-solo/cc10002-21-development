import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'

import Overview from './views/Overview'
import MetricdefView from './views/metricdef'
import DimensionView from './views/dimension'
import DatasourceView from './views/datasource'
import AggregationView from './views/aggregation'
import DashboardView from './views/dashboard'
import CollabView from './views/collab'
import CohortView from './views/cohort'
import AbtestView from './views/abtest'
import ReportView from './views/report'
import AlertView from './views/alert'
import DatamineView from './views/datamine'
import ApiView from './views/api'
import EtljobView from './views/etljob'
import QualityView from './views/quality'
import DatamodelView from './views/datamodel'
import ExportView from './views/export'
import SubscribeView from './views/subscribe'
import LineageView from './views/lineage'
import SegmentView from './views/segment'

const navItems = [{ label: "运营概览", path: "/" }, { label: "指标定义", path: "/metricdef" }, { label: "维度管理", path: "/dimension" }, { label: "数据源连接", path: "/datasource" }, { label: "聚合查询", path: "/aggregation" }, { label: "分析看板", path: "/dashboard" }, { label: "布局协作", path: "/collab" }, { label: "分群分析", path: "/cohort" }, { label: "AB实验", path: "/abtest" }, { label: "分析报告", path: "/report" }, { label: "指标预警", path: "/alert" }, { label: "数据挖掘", path: "/datamine" }, { label: "数据API", path: "/api" }, { label: "ETL任务", path: "/etljob" }, { label: "数据质量", path: "/quality" }, { label: "数据建模", path: "/datamodel" }, { label: "数据导出", path: "/export" }, { label: "数据订阅", path: "/subscribe" }, { label: "数据血缘", path: "/lineage" }, { label: "人群圈选", path: "/segment" }]

export default function App() {
  const [operator] = useState('值班管理员')

  return (
    <div className="app-shell">
      <aside className="app-side">
        <h1 className="app-title">数据指标分析平台</h1>
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link key={item.path} to={item.path} className="nav-item">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        <header className="app-head">
          <span className="head-desc">面向指标口径定义、多维度聚合分析、AB实验评估、数据服务发布与数据应用交付的数据指标分析平台。</span>
          <span className="head-user">当前值班：{operator}</span>
        </header>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/metricdef" element={<MetricdefView />} />
          <Route path="/dimension" element={<DimensionView />} />
          <Route path="/datasource" element={<DatasourceView />} />
          <Route path="/aggregation" element={<AggregationView />} />
          <Route path="/dashboard" element={<DashboardView />} />
          <Route path="/collab" element={<CollabView />} />
          <Route path="/cohort" element={<CohortView />} />
          <Route path="/abtest" element={<AbtestView />} />
          <Route path="/report" element={<ReportView />} />
          <Route path="/alert" element={<AlertView />} />
          <Route path="/datamine" element={<DatamineView />} />
          <Route path="/api" element={<ApiView />} />
          <Route path="/etljob" element={<EtljobView />} />
          <Route path="/quality" element={<QualityView />} />
          <Route path="/datamodel" element={<DatamodelView />} />
          <Route path="/export" element={<ExportView />} />
          <Route path="/subscribe" element={<SubscribeView />} />
          <Route path="/lineage" element={<LineageView />} />
          <Route path="/segment" element={<SegmentView />} />
        </Routes>
      </main>
    </div>
  )
}
