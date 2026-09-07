package com.clearpath.nexus.data.repository

import com.clearpath.nexus.data.model.RouteEvaluateResponse
import com.clearpath.nexus.data.model.ScoreBreakdown
import com.clearpath.nexus.data.model.SegmentPath
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class EvidenceGateAggregationTest {
    @Test
    fun `decision precedence is fail closed`() {
        assertEquals("HARD_BLOCKED", strictestDecisionState(listOf("READY", "HOLD", "HARD_BLOCKED")))
        assertEquals("UNAVAILABLE", strictestDecisionState(listOf("READY", "UNAVAILABLE", "HOLD")))
        assertEquals("HOLD", strictestDecisionState(listOf("READY", "HOLD")))
        assertEquals("UNAVAILABLE", strictestDecisionState(listOf("READY", "UNKNOWN")))
    }

    @Test
    fun `multi stop aggregation preserves every route id and worst leg`() {
        val first = leg("route-a", "READY", 91, 2.5, "segment-a")
        val second = leg("route-b", "UNAVAILABLE", 76, 3.0, "segment-b")
        val result = aggregateRouteLegs(listOf(first, second))

        assertEquals(listOf("route-a", "route-b"), result.routeIds)
        assertEquals("route-b", result.routeId)
        assertEquals("UNAVAILABLE", result.decisionState)
        assertEquals(76, result.reliabilityScore)
        assertEquals(5.5, result.estimatedHours!!, 0.001)
        assertEquals(listOf("segment-a", "segment-b"), result.segments.map { it.id })
    }

    @Test
    fun `missing leg metrics remain unavailable`() {
        val complete = leg("route-a", "READY", 91, 2.5, "segment-a")
        val missing = leg("route-b", "HOLD", 80, null, "segment-b").copy(scoreBreakdown = null)
        val result = aggregateRouteLegs(listOf(complete, missing))

        assertNull(result.estimatedHours)
        assertNull(result.scoreBreakdown)
    }

    private fun leg(
        id: String,
        decision: String,
        reliability: Int,
        hours: Double?,
        segmentId: String,
    ) = RouteEvaluateResponse(
        routeId = id,
        status = "APPROVED",
        decisionState = decision,
        reliabilityScore = reliability,
        estimatedHours = hours,
        scoreBreakdown = ScoreBreakdown(80.0, 70.0, 90.0, 85.0),
        segments = listOf(SegmentPath(segmentId, "APPROVED", emptyList())),
    )
}
