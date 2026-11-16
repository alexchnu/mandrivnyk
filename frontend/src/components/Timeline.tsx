import { DndContext, type DragEndEvent, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { AlertTriangle, ArrowDown, ArrowUp, Clock, Footprints, GripVertical, Trash2 } from 'lucide-react'
import { Fragment } from 'react'
import { dayColor } from '../lib/categories'
import { clock, dayLabel, distance, duration } from '../lib/format'
import { useT } from '../lib/i18n'
import type { PlanWarning, Visit } from '../lib/types'

export interface TimelineItem {
  id: string
  name: string
  category: string
  visitMinutes: number
  visit: Visit | null // null until the timetable is computed
}

interface Props {
  day: number
  items: TimelineItem[]
  warnings: PlanWarning[]
  focused: string | null
  onFocus?: (id: string | null) => void
  // editing callbacks; a read-only timeline passes none
  onMove?: (from: number, to: number) => void
  onRemove?: (id: string) => void
  onMoveToDay?: (id: string, day: number) => void
  dayCount?: number
  startDate?: string | null
}

interface RowProps extends Omit<Props, 'items' | 'warnings'> {
  item: TimelineItem
  index: number
  count: number
  problem: PlanWarning | undefined
  waits: PlanWarning | undefined
}

function Row({ item, index, count, problem, waits, day, focused, onFocus, onMove, onRemove, onMoveToDay, dayCount = 1, startDate = null }: RowProps) {
  const { t, lang } = useT()
  const editable = Boolean(onMove)
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.id, disabled: !editable })
  const visit = item.visit
  return (
    <li
      ref={setNodeRef}
      className={`stop${problem ? ' stop--problem' : ''}${isDragging ? ' stop--dragging' : ''}`}
      style={{ transform: CSS.Translate.toString(transform), transition, zIndex: isDragging ? 5 : undefined }}
      onMouseEnter={() => onFocus?.(item.id)}
      onMouseLeave={() => onFocus?.(null)}
      data-stop={item.id}
    >
      <div className="stop__time">
        {visit ? (
          <>
            <div className="stop__arrive">{clock(visit.start)}</div>
            <div className="stop__leave">{clock(visit.leave)}</div>
          </>
        ) : (
          <div className="stop__leave">—</div>
        )}
      </div>
      <div className="stop__node" style={focused === item.id ? { outline: '3px solid var(--mark)' } : undefined}>
        {index + 1}
      </div>
      <div className="stop__body">
        <div className="stop__row">
          <div className="stop__name">{item.name}</div>
          {editable && (
            <button type="button" className="icon-btn stop__handle" aria-label={t('trip.drag')} title={t('trip.drag')} {...attributes} {...listeners}>
              <GripVertical size={18} />
            </button>
          )}
        </div>
        <div className="stop__meta">
          {t(`cat.${item.category}` as never)}, {duration(item.visitMinutes, lang)}
        </div>
        {problem && (
          <div className="flag flag--bad">
            <AlertTriangle aria-hidden="true" />
            {t(problem.code === 'closed' ? 'warn.closed' : 'warn.late')}
          </div>
        )}
        {waits && (
          <div className="flag flag--warn">
            <Clock aria-hidden="true" />
            {t('warn.waits', { t: duration(waits.minutes ?? 0, lang) })}
          </div>
        )}
        {editable && (
          <div className="stop__tools">
            <button type="button" className="icon-btn" disabled={index === 0} onClick={() => onMove?.(index, index - 1)} aria-label={t('trip.moveUp')} title={t('trip.moveUp')}>
              <ArrowUp size={17} />
            </button>
            <button type="button" className="icon-btn" disabled={index === count - 1} onClick={() => onMove?.(index, index + 1)} aria-label={t('trip.moveDown')} title={t('trip.moveDown')}>
              <ArrowDown size={17} />
            </button>
            <button type="button" className="icon-btn" onClick={() => onRemove?.(item.id)} aria-label={t('trip.remove')} title={t('trip.remove')}>
              <Trash2 size={17} />
            </button>
            {dayCount > 1 && (
              <select aria-label={t('trip.toDay')} value={day} onChange={(e) => onMoveToDay?.(item.id, Number(e.target.value))}>
                {Array.from({ length: dayCount }, (_, d) => (
                  <option key={d} value={d}>
                    {dayLabel(startDate, d, lang)}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

export function Timeline(props: Props) {
  const { t, lang } = useT()
  const { items, warnings, day, onMove } = props
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  function onDragEnd(event: DragEndEvent) {
    if (!event.over || event.active.id === event.over.id) return
    const from = items.findIndex((i) => i.id === event.active.id)
    const to = items.findIndex((i) => i.id === event.over?.id)
    if (from >= 0 && to >= 0) onMove?.(from, to)
  }

  const visits = items.map((i) => i.visit).filter((v): v is Visit => v !== null)
  const walk = visits.reduce((sum, v) => sum + v.walk_minutes, 0)
  const walkMeters = visits.reduce((sum, v) => sum + v.walk_meters, 0)
  const onSite = visits.reduce((sum, v) => sum + (v.leave - v.start), 0)
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={items.map((i) => i.id)} strategy={verticalListSortingStrategy}>
        <ol className="timeline" style={{ ['--day' as string]: dayColor(day) }}>
          {items.map((item, index) => (
            <Fragment key={item.id}>
              {index > 0 && (
                <li className="leg" aria-hidden={!item.visit}>
                  {item.visit && (
                    <span>
                      <Footprints />
                      {t('trip.walk', { t: duration(item.visit.walk_minutes, lang) })}, {distance(item.visit.walk_meters, lang)}
                    </span>
                  )}
                </li>
              )}
              <Row
                {...props}
                item={item}
                index={index}
                count={items.length}
                problem={warnings.find((w) => w.poi_id === item.id && (w.code === 'closed' || w.code === 'late'))}
                waits={warnings.find((w) => w.poi_id === item.id && w.code === 'waits')}
              />
            </Fragment>
          ))}
          {visits.length > 0 && visits.length === items.length && (
            <li className="day-total">
              <strong>{t('trip.total')}</strong>
              {t('trip.totalWalk', { t: duration(walk, lang) })} ({distance(walkMeters, lang)}), {t('trip.totalVisit', { t: duration(onSite, lang) })},{' '}
              {t('trip.finish', { t: clock(visits[visits.length - 1].leave) })}
            </li>
          )}
        </ol>
      </SortableContext>
    </DndContext>
  )
}
